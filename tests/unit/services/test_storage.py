"""Tests for services/storage.py — Supabase Storage image operations.

Covers: upload (success/failure), download (success/failure),
cleanup (success/no files/list failure), signed URL failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from bot.exceptions import AppError
from services.storage import BUCKET, SIGNED_URL_TTL, ImageStorage, StoredImage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_URL = "https://test.supabase.co"
FAKE_KEY = "test-service-role-key"
BASE_STORAGE = f"{FAKE_URL}/storage/v1"


@pytest.fixture
def mock_http() -> AsyncMock:
    """Mock httpx.AsyncClient with spec for type safety."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def storage(mock_http: AsyncMock) -> ImageStorage:
    return ImageStorage(
        supabase_url=FAKE_URL,
        supabase_key=FAKE_KEY,
        http_client=mock_http,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_bucket_name(self) -> None:
        assert BUCKET == "content-images"

    def test_signed_url_ttl(self) -> None:
        assert SIGNED_URL_TTL == 90000


# ---------------------------------------------------------------------------
# StoredImage dataclass
# ---------------------------------------------------------------------------


class TestStoredImage:
    def test_fields(self) -> None:
        img = StoredImage(path="previews/1/0.png", signed_url="https://example.com/signed")
        assert img.path == "previews/1/0.png"
        assert img.signed_url == "https://example.com/signed"


# ---------------------------------------------------------------------------
# ImageStorage.upload
# ---------------------------------------------------------------------------


class TestUpload:
    async def test_upload_png_success_returns_stored_image(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() with PNG returns StoredImage with correct path and signed URL."""
        image_bytes = b"\x89PNG\r\n\x1a\nfake"
        preview_id = 42
        index = 0
        expected_path = f"previews/{preview_id}/{index}.png"
        signed_suffix = "/object/sign/content-images/token123"

        # Upload response (200)
        upload_resp = httpx.Response(200, json={"Key": expected_path})
        # Signed URL response (200)
        sign_resp = httpx.Response(200, json={"signedURL": signed_suffix})

        mock_http.post.side_effect = [upload_resp, sign_resp]

        result = await storage.upload(image_bytes, preview_id, index, mime="image/png")

        assert isinstance(result, StoredImage)
        assert result.path == expected_path
        assert result.signed_url == f"{BASE_STORAGE}{signed_suffix}"

        # Verify upload call
        upload_call = mock_http.post.call_args_list[0]
        assert upload_call[0][0] == f"{BASE_STORAGE}/object/{BUCKET}/{expected_path}"
        assert upload_call[1]["content"] == image_bytes
        assert upload_call[1]["headers"]["Content-Type"] == "image/png"
        assert upload_call[1]["headers"]["x-upsert"] == "true"
        assert upload_call[1]["headers"]["apikey"] == FAKE_KEY

        # Verify signed URL call
        sign_call = mock_http.post.call_args_list[1]
        assert sign_call[0][0] == f"{BASE_STORAGE}/object/sign/{BUCKET}/{expected_path}"
        assert sign_call[1]["json"] == {"expiresIn": SIGNED_URL_TTL}

    async def test_upload_jpg_success_uses_jpg_extension(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() with JPEG mime produces .jpg extension."""
        expected_path = "previews/10/2.jpg"
        upload_resp = httpx.Response(200, json={"Key": expected_path})
        sign_resp = httpx.Response(200, json={"signedURL": "/signed/url"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        result = await storage.upload(b"jpeg-data", 10, 2, mime="image/jpeg")

        assert result.path == expected_path
        assert result.path.endswith(".jpg")

    async def test_upload_status_201_success(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() also accepts 201 Created from Supabase Storage."""
        upload_resp = httpx.Response(201, json={"Key": "previews/1/0.png"})
        sign_resp = httpx.Response(200, json={"signedURL": "/signed"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        result = await storage.upload(b"data", 1, 0)

        assert result.path == "previews/1/0.png"

    async def test_upload_failure_non200_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError when storage returns non-200/201."""
        upload_resp = httpx.Response(403, json={"error": "Forbidden"})
        mock_http.post.return_value = upload_resp

        with pytest.raises(AppError, match="Storage upload failed: 403"):
            await storage.upload(b"data", 1, 0)

    async def test_upload_failure_500_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError on server error."""
        upload_resp = httpx.Response(500, text="Internal Server Error")
        mock_http.post.return_value = upload_resp

        with pytest.raises(AppError, match="Storage upload failed: 500"):
            await storage.upload(b"data", 5, 3)

    async def test_upload_signed_url_failure_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError when signed URL creation fails."""
        upload_resp = httpx.Response(200, json={"Key": "previews/1/0.png"})
        sign_resp = httpx.Response(500, json={"error": "internal"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        with pytest.raises(AppError, match="Signed URL creation failed: 500"):
            await storage.upload(b"data", 1, 0)

    async def test_upload_default_mime_is_png(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() defaults to image/png when mime is not specified."""
        upload_resp = httpx.Response(200, json={"Key": "previews/1/0.png"})
        sign_resp = httpx.Response(200, json={"signedURL": "/signed"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        result = await storage.upload(b"data", 1, 0)

        assert result.path == "previews/1/0.png"
        upload_call = mock_http.post.call_args_list[0]
        assert upload_call[1]["headers"]["Content-Type"] == "image/png"


# ---------------------------------------------------------------------------
# ImageStorage.download
# ---------------------------------------------------------------------------


class TestDownload:
    async def test_download_success_returns_bytes(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """download() returns raw image bytes on success."""
        image_data = b"\x89PNG\r\n\x1a\nfake-image-content"
        path = "previews/42/0.png"
        mock_http.get.return_value = httpx.Response(200, content=image_data)

        result = await storage.download(path)

        assert result == image_data
        mock_http.get.assert_awaited_once_with(
            f"{BASE_STORAGE}/object/{BUCKET}/{path}",
            headers={
                "apikey": FAKE_KEY,
                "Authorization": f"Bearer {FAKE_KEY}",
            },
        )

    async def test_download_failure_404_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """download() raises AppError when file not found."""
        mock_http.get.return_value = httpx.Response(404, json={"error": "Not Found"})

        with pytest.raises(AppError, match="Storage download failed: 404"):
            await storage.download("previews/99/0.png")

    async def test_download_failure_500_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """download() raises AppError on server error."""
        mock_http.get.return_value = httpx.Response(500, text="Server Error")

        with pytest.raises(AppError, match="Storage download failed: 500"):
            await storage.download("previews/1/0.png")


# ---------------------------------------------------------------------------
# ImageStorage.cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    async def test_cleanup_success_deletes_and_returns_count(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup() lists files, deletes them, and returns count."""
        preview_id = 42
        files = [{"name": "0.png"}, {"name": "1.jpg"}, {"name": "2.png"}]

        list_resp = httpx.Response(200, json=files)
        delete_resp = httpx.Response(200, json=[])
        mock_http.post.side_effect = [list_resp, delete_resp]

        result = await storage.cleanup(preview_id)

        assert result == 3

        # Verify list call
        list_call = mock_http.post.call_args_list[0]
        assert list_call[0][0] == f"{BASE_STORAGE}/object/list/{BUCKET}"
        assert list_call[1]["json"] == {"prefix": f"previews/{preview_id}/", "limit": 100}

        # Verify delete call
        delete_call = mock_http.post.call_args_list[1]
        assert delete_call[0][0] == f"{BASE_STORAGE}/object/remove/{BUCKET}"
        expected_paths = [
            f"previews/{preview_id}/0.png",
            f"previews/{preview_id}/1.jpg",
            f"previews/{preview_id}/2.png",
        ]
        assert delete_call[1]["json"] == expected_paths

    async def test_cleanup_no_files_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup() returns 0 when directory is empty."""
        list_resp = httpx.Response(200, json=[])
        mock_http.post.return_value = list_resp

        result = await storage.cleanup(99)

        assert result == 0
        # Only one call (list), no delete call
        assert mock_http.post.await_count == 1

    async def test_cleanup_list_failure_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup() returns 0 when listing files fails (non-200)."""
        list_resp = httpx.Response(500, json={"error": "internal"})
        mock_http.post.return_value = list_resp

        result = await storage.cleanup(77)

        assert result == 0
        # Only one call (list), no delete call
        assert mock_http.post.await_count == 1

    async def test_cleanup_delete_failure_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup() returns 0 when delete request fails."""
        files = [{"name": "0.png"}]
        list_resp = httpx.Response(200, json=files)
        delete_resp = httpx.Response(500, json={"error": "delete failed"})
        mock_http.post.side_effect = [list_resp, delete_resp]

        result = await storage.cleanup(10)

        assert result == 0

    async def test_cleanup_single_file_returns_one(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup() correctly handles single file."""
        files = [{"name": "0.png"}]
        list_resp = httpx.Response(200, json=files)
        delete_resp = httpx.Response(200, json=[])
        mock_http.post.side_effect = [list_resp, delete_resp]

        result = await storage.cleanup(5)

        assert result == 1


# ---------------------------------------------------------------------------
# ImageStorage.__init__ — headers and base URL
# ---------------------------------------------------------------------------


class TestInit:
    def test_base_url_constructed(self, storage: ImageStorage) -> None:
        assert storage._base_url == f"{FAKE_URL}/storage/v1"

    def test_headers_contain_apikey(self, storage: ImageStorage) -> None:
        assert storage._headers["apikey"] == FAKE_KEY

    def test_headers_contain_authorization(self, storage: ImageStorage) -> None:
        assert storage._headers["Authorization"] == f"Bearer {FAKE_KEY}"

    def test_http_client_stored(self, storage: ImageStorage, mock_http: AsyncMock) -> None:
        assert storage._http is mock_http
