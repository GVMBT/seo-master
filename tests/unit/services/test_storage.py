"""Tests for services/storage.py — Supabase Storage image operations.

Covers: upload (success/failure/WebP conversion/fallback), download (success/failure),
cleanup_by_paths, cleanup_prefix, signed URL failure, WebP conversion (E33).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
        img = StoredImage(path="123/456/1000_0.webp", signed_url="https://example.com/signed")
        assert img.path == "123/456/1000_0.webp"
        assert img.signed_url == "https://example.com/signed"


# ---------------------------------------------------------------------------
# ImageStorage.upload
# ---------------------------------------------------------------------------


class TestUpload:
    @patch("services.storage.time")
    async def test_upload_webp_success_returns_stored_image(
        self,
        mock_time: AsyncMock,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() converts to WebP and returns StoredImage with correct path."""
        mock_time.time.return_value = 1700000000
        user_id = 123
        project_id = 456
        index = 0
        # WebP conversion is mocked — just test path format
        signed_suffix = "/object/sign/content-images/token123"

        upload_resp = httpx.Response(200, json={"Key": "ok"})
        sign_resp = httpx.Response(200, json={"signedURL": signed_suffix})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        # Patch _convert_to_webp to avoid needing Pillow
        with patch.object(
            ImageStorage,
            "_convert_to_webp",
            return_value=(b"webp-data", "webp", "image/webp"),
        ):
            result = await storage.upload(b"png-data", user_id, project_id, index, mime="image/png")

        assert isinstance(result, StoredImage)
        assert result.path == "123/456/1700000000_0.webp"
        assert result.signed_url == f"{BASE_STORAGE}{signed_suffix}"

        # Verify upload call uses webp mime
        upload_call = mock_http.post.call_args_list[0]
        assert upload_call[1]["headers"]["Content-Type"] == "image/webp"
        assert upload_call[1]["headers"]["x-upsert"] == "true"
        assert upload_call[1]["content"] == b"webp-data"

    @patch("services.storage.time")
    async def test_upload_webp_fallback_uses_original_ext(
        self,
        mock_time: AsyncMock,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() falls back to original format when WebP conversion fails (E33)."""
        mock_time.time.return_value = 1700000000

        upload_resp = httpx.Response(200, json={"Key": "ok"})
        sign_resp = httpx.Response(200, json={"signedURL": "/signed"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        # _convert_to_webp returns original format on failure
        with patch.object(
            ImageStorage,
            "_convert_to_webp",
            return_value=(b"jpeg-data", "jpg", "image/jpeg"),
        ):
            result = await storage.upload(b"jpeg-data", 1, 2, 0, mime="image/jpeg")

        assert result.path == "1/2/1700000000_0.jpg"

    async def test_upload_failure_non200_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError when storage returns non-200/201."""
        upload_resp = httpx.Response(403, json={"error": "Forbidden"})
        mock_http.post.return_value = upload_resp

        with (
            patch.object(
                ImageStorage,
                "_convert_to_webp",
                return_value=(b"data", "webp", "image/webp"),
            ),
            pytest.raises(AppError, match="Storage upload failed: 403"),
        ):
            await storage.upload(b"data", 1, 2, 0)

    async def test_upload_failure_500_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError on server error."""
        upload_resp = httpx.Response(500, text="Internal Server Error")
        mock_http.post.return_value = upload_resp

        with (
            patch.object(
                ImageStorage,
                "_convert_to_webp",
                return_value=(b"data", "webp", "image/webp"),
            ),
            pytest.raises(AppError, match="Storage upload failed: 500"),
        ):
            await storage.upload(b"data", 5, 3, 0)

    async def test_upload_signed_url_failure_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """upload() raises AppError when signed URL creation fails."""
        upload_resp = httpx.Response(200, json={"Key": "ok"})
        sign_resp = httpx.Response(500, json={"error": "internal"})
        mock_http.post.side_effect = [upload_resp, sign_resp]

        with (
            patch.object(
                ImageStorage,
                "_convert_to_webp",
                return_value=(b"data", "webp", "image/webp"),
            ),
            pytest.raises(AppError, match="Signed URL creation failed: 500"),
        ):
            await storage.upload(b"data", 1, 2, 0)


# ---------------------------------------------------------------------------
# ImageStorage._convert_to_webp
# ---------------------------------------------------------------------------


class TestConvertToWebp:
    def test_fallback_on_error_returns_original_png(self) -> None:
        """_convert_to_webp falls back to original when PIL fails (E33)."""
        # Invalid image data will cause PIL to fail
        result_bytes, ext, mime = ImageStorage._convert_to_webp(b"not-an-image", "image/png")
        assert ext == "png"
        assert mime == "image/png"
        assert result_bytes == b"not-an-image"

    def test_fallback_on_error_returns_original_jpg(self) -> None:
        """_convert_to_webp falls back to jpg for JPEG mime."""
        _result_bytes, ext, mime = ImageStorage._convert_to_webp(b"not-an-image", "image/jpeg")
        assert ext == "jpg"
        assert mime == "image/jpeg"


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
        path = "123/456/1700000000_0.webp"
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
            await storage.download("123/456/0.webp")

    async def test_download_failure_500_raises_app_error(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """download() raises AppError on server error."""
        mock_http.get.return_value = httpx.Response(500, text="Server Error")

        with pytest.raises(AppError, match="Storage download failed: 500"):
            await storage.download("123/456/0.webp")


# ---------------------------------------------------------------------------
# ImageStorage.cleanup_by_paths
# ---------------------------------------------------------------------------


class TestCleanupByPaths:
    async def test_cleanup_by_paths_success(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_by_paths() deletes specified files and returns count."""
        paths = ["123/456/1_0.webp", "123/456/1_1.webp"]
        delete_resp = httpx.Response(200, json=[])
        mock_http.post.return_value = delete_resp

        result = await storage.cleanup_by_paths(paths)

        assert result == 2
        mock_http.post.assert_awaited_once_with(
            f"{BASE_STORAGE}/object/remove/{BUCKET}",
            json=paths,
            headers={**storage._headers, "Content-Type": "application/json"},
        )

    async def test_cleanup_by_paths_empty_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_by_paths() returns 0 for empty paths list."""
        result = await storage.cleanup_by_paths([])
        assert result == 0
        mock_http.post.assert_not_awaited()

    async def test_cleanup_by_paths_failure_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_by_paths() returns 0 when delete fails."""
        delete_resp = httpx.Response(500, json={"error": "fail"})
        mock_http.post.return_value = delete_resp

        result = await storage.cleanup_by_paths(["123/456/0.webp"])
        assert result == 0


# ---------------------------------------------------------------------------
# ImageStorage.cleanup_prefix
# ---------------------------------------------------------------------------


class TestCleanupPrefix:
    async def test_cleanup_prefix_success(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_prefix() lists and deletes files under prefix."""
        files = [{"name": "1700000000_0.webp"}, {"name": "1700000000_1.webp"}]
        list_resp = httpx.Response(200, json=files)
        delete_resp = httpx.Response(200, json=[])
        mock_http.post.side_effect = [list_resp, delete_resp]

        result = await storage.cleanup_prefix("123/456/")

        assert result == 2

        # Verify list call
        list_call = mock_http.post.call_args_list[0]
        assert list_call[0][0] == f"{BASE_STORAGE}/object/list/{BUCKET}"
        assert list_call[1]["json"] == {"prefix": "123/456/", "limit": 100}

        # Verify delete call
        delete_call = mock_http.post.call_args_list[1]
        assert delete_call[1]["json"] == [
            "123/456/1700000000_0.webp",
            "123/456/1700000000_1.webp",
        ]

    async def test_cleanup_prefix_no_files_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_prefix() returns 0 when directory is empty."""
        list_resp = httpx.Response(200, json=[])
        mock_http.post.return_value = list_resp

        result = await storage.cleanup_prefix("123/456/")
        assert result == 0
        assert mock_http.post.await_count == 1

    async def test_cleanup_prefix_list_failure_returns_zero(
        self,
        storage: ImageStorage,
        mock_http: AsyncMock,
    ) -> None:
        """cleanup_prefix() returns 0 when listing files fails."""
        list_resp = httpx.Response(500, json={"error": "internal"})
        mock_http.post.return_value = list_resp

        result = await storage.cleanup_prefix("123/456/")
        assert result == 0
        assert mock_http.post.await_count == 1


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
