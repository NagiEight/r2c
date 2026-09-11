import base64
import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Generator
from datetime import datetime
from typing import Self
from urllib.parse import quote, unquote

import httpx
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from features.manage.domain.entities import R2HttpConfig, R2Object, R2ObjectSummary
from features.manage.domain.ports import R2AdapterPort


class HTTPR2Adapter(R2AdapterPort):
    def __init__(
        self, config: R2HttpConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._host = f"{config.account_id}.r2.cloudflarestorage.com"
        self._credentials = Credentials(
            config.access_key_id, config.secret_access_key
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()


    def _sign_and_build_headers(
        self,
        method: str,
        key: str = "",
        query_params: str = "",
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        clean_key = unquote(key.lstrip("/"))
        encoded_key = quote(clean_key, safe="/")

        path = (
            f"/{self._config.bucket_name}/{encoded_key}"
            if clean_key
            else f"/{self._config.bucket_name}"
        )

        url = f"https://{self._host}{path}"
        if query_params:
            url += f"?{query_params}"

        payload_hash = hashlib.sha256(body).hexdigest()

        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
        }
        if extra_headers:
            for k, v in extra_headers.items():
                headers[k.lower()] = v

        request = AWSRequest(method=method, url=url, data=body, headers=headers)
        # Pin the exact signed path — do not let the signer re-derive it.
        request.auth_path = path
        S3SigV4Auth(self._credentials, "s3", "auto").add_auth(request)

        return url, dict(request.headers)

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        url, headers = self._sign_and_build_headers(
            method="PUT",
            key=key,
            body=data,
            extra_headers={"Content-Type": content_type},
        )
        response = await self._client.put(url, content=data, headers=headers)
        response.raise_for_status()

    async def fetch(self, key: str) -> R2Object:
        url, headers = self._sign_and_build_headers(method="GET", key=key)
        response = await self._client.get(url, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "application/octet-stream")
        return R2Object(key=key, content=response.content, content_type=content_type)

    async def delete(self, key: str) -> None:
        url, headers = self._sign_and_build_headers(method="DELETE", key=key)
        response = await self._client.delete(url, headers=headers)
        response.raise_for_status()

    async def copy(self, source_key: str, destination_key: str) -> None:
        copy_source = quote(
            f"/{self._config.bucket_name}/{source_key.lstrip('/')}", safe="/"
        )
        url, headers = self._sign_and_build_headers(
            method="PUT",
            key=destination_key,
            extra_headers={"x-amz-copy-source": copy_source},
        )
        response = await self._client.put(url, headers=headers)
        response.raise_for_status()

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return

        for chunk in self._chunk_list(keys, size=1000):
            root = ET.Element("Delete")
            for key in chunk:
                obj = ET.SubElement(root, "Object")
                key_node = ET.SubElement(obj, "Key")
                key_node.text = key

            xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            content_md5 = base64.b64encode(hashlib.md5(xml_body).digest()).decode(
                "utf-8"
            )

            url, headers = self._sign_and_build_headers(
                method="POST",
                query_params="delete",
                body=xml_body,
                extra_headers={
                    "Content-Type": "application/xml",
                    "Content-MD5": content_md5,
                },
            )

            response = await self._client.post(
                url, content=xml_body, headers=headers
            )
            response.raise_for_status()

    async def list_keys(self, prefix: str = "") -> list[str]:
        objects = await self.list_objects(prefix=prefix)
        return [obj.key for obj in objects]

    async def list_objects(self, prefix: str = "") -> list[R2ObjectSummary]:
        items: list[R2ObjectSummary] = []
        continuation_token: str | None = None

        while True:
            params = ["list-type=2"]
            if prefix:
                params.append(f"prefix={quote(prefix, safe='/')}")
            if continuation_token:
                params.append(
                    f"continuation-token={quote(continuation_token, safe='')}"
                )

            query_params = "&".join(params)
            url, headers = self._sign_and_build_headers(
                method="GET", query_params=query_params
            )

            response = await self._client.get(url, headers=headers)
            response.raise_for_status()

            root = ET.fromstring(response.text)
            ns = {"s3": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

            contents = (
                root.findall("s3:Contents", ns) if ns else root.findall("Contents")
            )
            for node in contents:
                key = self._get_text(node, "Key", ns)
                size_str = self._get_text(node, "Size", ns)
                date_str = self._get_text(node, "LastModified", ns)

                if key:
                    size = int(size_str) if size_str and size_str.isdigit() else 0
                    last_modified = (
                        datetime.fromisoformat(date_str)
                        if date_str
                        else None
                    )

                    items.append(
                        R2ObjectSummary(
                            key=key,
                            size_bytes=size,
                            last_modified=last_modified,
                        )
                    )

            is_truncated_str = self._get_text(root, "IsTruncated", ns)
            is_truncated = (
                is_truncated_str is not None
                and is_truncated_str.lower() == "true"
            )

            if not is_truncated:
                break

            continuation_token = self._get_text(root, "NextContinuationToken", ns)
            if not continuation_token:
                break

        return items

    @staticmethod
    def _get_text(
        element: ET.Element, tag_name: str, ns: dict[str, str]
    ) -> str | None:
        path = f"s3:{tag_name}" if ns else tag_name
        return element.findtext(path, namespaces=ns)

    @staticmethod
    def _chunk_list(items: list[str], size: int) -> Generator[list[str], None, None]:
        for i in range(0, len(items), size):
            yield items[i : i + size]
