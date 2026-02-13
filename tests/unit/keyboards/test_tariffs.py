"""Tests for tariff keyboards in keyboards/inline.py."""

from __future__ import annotations

from keyboards.inline import (
    package_list_kb,
    package_pay_kb,
    subscription_cancel_confirm_kb,
    subscription_manage_kb,
    subscription_pay_kb,
    tariffs_main_kb,
)


class TestTariffsMainKb:
    def test_without_subscription(self) -> None:
        kb = tariffs_main_kb(has_subscription=False)
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Пополнить" in t for t in texts)
        assert "Моя подписка" not in texts

    def test_with_subscription(self) -> None:
        kb = tariffs_main_kb(has_subscription=True)
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Моя подписка" in t for t in texts)

    def test_has_main_menu_button(self) -> None:
        kb = tariffs_main_kb()
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Главное меню" in t for t in texts)


class TestPackageListKb:
    def test_has_five_packages(self) -> None:
        kb = package_list_kb()
        markup = kb.as_markup()
        # 5 packages + 1 back button = 6 rows
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        pkg_data = [d for d in data if d and d.startswith("tariff:") and d.endswith(":select")]
        assert len(pkg_data) == 5

    def test_has_back_button(self) -> None:
        kb = package_list_kb()
        markup = kb.as_markup()
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "tariffs:main" in data


class TestPackagePayKb:
    def test_has_stars_and_yookassa(self) -> None:
        kb = package_pay_kb("mini")
        markup = kb.as_markup()
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "tariff:mini:stars" in data
        assert "tariff:mini:yk" in data

    def test_show_savings_for_business(self) -> None:
        kb = package_pay_kb("business", show_savings=True)
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("экономии" in t for t in texts)

    def test_no_savings_for_mini(self) -> None:
        kb = package_pay_kb("mini", show_savings=False)
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert not any("экономии" in t for t in texts)


class TestSubscriptionPayKb:
    def test_has_stars_and_yookassa(self) -> None:
        kb = subscription_pay_kb("pro")
        markup = kb.as_markup()
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "sub:pro:stars" in data
        assert "sub:pro:yk" in data


class TestSubscriptionManageKb:
    def test_has_cancel_button(self) -> None:
        kb = subscription_manage_kb()
        markup = kb.as_markup()
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "sub:cancel" in data

    def test_has_change_plan_button(self) -> None:
        kb = subscription_manage_kb()
        markup = kb.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Изменить тариф" in t for t in texts)


class TestSubscriptionCancelConfirmKb:
    def test_has_confirm_and_back(self) -> None:
        kb = subscription_cancel_confirm_kb()
        markup = kb.as_markup()
        data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "sub:cancel:confirm" in data
        assert "sub:manage" in data
