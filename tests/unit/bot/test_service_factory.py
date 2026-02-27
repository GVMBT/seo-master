"""Tests for bot/service_factory.py — TokenServiceFactory, ConnectionServiceFactory."""

from unittest.mock import MagicMock, patch

from bot.service_factory import (
    ConnectionServiceFactory,
    TokenServiceFactory,
    create_connection_service_factory,
    create_token_service_factory,
)


class TestTokenServiceFactory:
    def test_create_factory(self) -> None:
        factory = create_token_service_factory([123, 456])
        assert isinstance(factory, TokenServiceFactory)

    def test_factory_creates_service(self) -> None:
        factory = TokenServiceFactory(admin_ids=[42])
        mock_db = MagicMock()

        with patch("bot.service_factory.TokenService") as MockTS:
            result = factory(mock_db)
            MockTS.assert_called_once_with(db=mock_db, admin_ids=[42])
            assert result is MockTS.return_value

    def test_factory_preserves_admin_ids(self) -> None:
        factory = TokenServiceFactory(admin_ids=[1, 2, 3])
        assert factory._admin_ids == [1, 2, 3]


class TestConnectionServiceFactory:
    def test_create_factory(self) -> None:
        factory = create_connection_service_factory()
        assert isinstance(factory, ConnectionServiceFactory)

    def test_factory_creates_service(self) -> None:
        factory = ConnectionServiceFactory()
        mock_db = MagicMock()
        mock_http = MagicMock()

        with patch("bot.service_factory.ConnectionService") as MockCS:
            result = factory(mock_db, mock_http)
            MockCS.assert_called_once_with(db=mock_db, http_client=mock_http)
            assert result is MockCS.return_value
