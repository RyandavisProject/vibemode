import unittest

from neurogate_usage_overlay.parser import parse_usage_text


class UsageParserTest(unittest.TestCase):
    def test_parse_usage_text_from_russian_page_copy(self):
        text = """
        Лимиты
        ascend
        МОДЕЛЬ
        Все модели
        ИСПОЛЬЗОВАНО
        1 718 659 626 токены
        Приблизительно осталось: 9 639 782 853
        24 часа · сброс 09:00 UTC
        Сброс через 14 ч 26 мин
        ТОКЕНЫ
        135 285 661
        КЕШ
        125 790 976
        ЛИМИТЫ ТАРИФА
        37 940 599 / 120 000 000
        7 дней
        Сброс через 2 д 10 ч
        ТОКЕНЫ
        985 751 421
        КЕШ
        923 269 248
        ЛИМИТЫ ТАРИФА
        249 659 909 / 600 000 000
        """

        snapshot = parse_usage_text(text)

        self.assertEqual(snapshot.account, "ascend")
        self.assertEqual(snapshot.model_group, "Все модели")
        self.assertEqual(snapshot.total_used, 1_718_659_626)
        self.assertEqual(snapshot.remaining, 9_639_782_853)
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.windows[0].title, "24 часа")
        self.assertEqual(snapshot.windows[0].tokens, 135_285_661)
        self.assertEqual(snapshot.windows[0].cache, 125_790_976)
        self.assertEqual(snapshot.windows[0].limit_used, 37_940_599)
        self.assertEqual(snapshot.windows[0].limit_total, 120_000_000)
        self.assertEqual(snapshot.windows[1].title, "7 дней")
        self.assertEqual(snapshot.windows[1].tokens, 985_751_421)
        self.assertEqual(snapshot.windows[1].cache, 923_269_248)
        self.assertEqual(snapshot.windows[1].limit_used, 249_659_909)
        self.assertEqual(snapshot.windows[1].limit_total, 600_000_000)

    def test_parse_new_credit_limits_page(self):
        text = """
        КАБИНЕТ КЛИЕНТА
        Лимиты
        Подробная информация о Вашем тарифе
        ascend
        активен ещё 2 д 20 ч
        ПЛАТНЫЙ СБРОС
        30 USDT
        Сбрасывает: 7 дней, 5 часов. Месячный лимит сохраняется.
        5 часов
        Сброс через 4 ч 53 мин
        118 492 616
        Кредитов осталось
        7 дней
        Сброс через 1 д 20 ч
        331 363 335
        Кредитов осталось
        ИСТОРИЯ
        Последние списания
        """

        snapshot = parse_usage_text(text)

        self.assertEqual(snapshot.account, "ascend")
        self.assertIsNone(snapshot.model_group)
        self.assertEqual(snapshot.plan_status, "активен ещё 2 д 20 ч")
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.windows[0].title, "5 часов")
        self.assertEqual(snapshot.windows[0].credits_remaining, 118_492_616)
        self.assertEqual(snapshot.windows[0].reset_text, "4 ч 53 мин")
        self.assertEqual(snapshot.windows[1].title, "7 дней")
        self.assertEqual(snapshot.windows[1].credits_remaining, 331_363_335)
        self.assertEqual(snapshot.windows[1].reset_text, "1 д 20 ч")


if __name__ == "__main__":
    unittest.main()
