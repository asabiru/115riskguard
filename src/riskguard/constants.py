"""Справочники, пороги и веса для rule-based движка.

Все значения основаны на публичной практике 2024–2026 годов:
обзоры кейсов банки.ру (banki.ru/forum), методические рекомендации
ЦБ РФ (МР 4-МР, МР 16-МР, 17-МР, 18-МР, 19-МР), положение 375-П и 519-П,
письма Росфинмониторинга.  Значения являются консервативной моделью —
не юридическим нормативом — и конфигурируются на лету в Streamlit-UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ----------------------------- уровни риска -----------------------------


class RiskLevel(str, Enum):
    """Итоговый уровень риска блокировки."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


LEVEL_LABELS_RU: dict[RiskLevel, str] = {
    RiskLevel.GREEN: "Зелёный — низкий риск",
    RiskLevel.YELLOW: "Жёлтый — повышенный риск",
    RiskLevel.RED: "Красный — высокий риск",
}

LEVEL_COLORS: dict[RiskLevel, str] = {
    RiskLevel.GREEN: "#2ea043",
    RiskLevel.YELLOW: "#f2a93b",
    RiskLevel.RED: "#d1242f",
}


# ----------------------------- канонические поля ------------------------

# Канонические колонки нормализованного DataFrame транзакций.
CANON_DATE = "date"
CANON_AMOUNT = "amount"  # подписанное значение: доход > 0, расход < 0
CANON_CURRENCY = "currency"
CANON_DESCRIPTION = "description"
CANON_COUNTERPARTY = "counterparty"
CANON_CATEGORY = "category"
CANON_BALANCE = "balance"
CANON_TYPE = "type"  # income | expense
CANON_CHANNEL = "channel"  # p2p | card | cash | atm | online | other
CANON_MCC = "mcc"

CANONICAL_COLUMNS: tuple[str, ...] = (
    CANON_DATE,
    CANON_AMOUNT,
    CANON_CURRENCY,
    CANON_DESCRIPTION,
    CANON_COUNTERPARTY,
    CANON_CATEGORY,
    CANON_BALANCE,
    CANON_TYPE,
    CANON_CHANNEL,
    CANON_MCC,
)


# ----------------------------- категории каналов ------------------------

# Ключевые слова для эвристического определения канала операции
# по description/category.  Нижний регистр, без склонений.
P2P_KEYWORDS: tuple[str, ...] = (
    "p2p",
    "перевод сбп",
    "сбп",
    "перевод с карты",
    "перевод на карту",
    "перевод другому",
    "перевод клиенту",
    "входящий перевод",
    "исходящий перевод",
    "card2card",
    "c2c",
    "перевод физическому",
    "перевод физлицу",
    "перевод по номеру телефона",
)

CASH_KEYWORDS: tuple[str, ...] = (
    "снятие наличных",
    "снятие",
    "внесение наличных",
    "внесение",
    "банкомат",
    "atm",
    "cash",
    "касса",
    "наличн",
)

CRYPTO_KEYWORDS: tuple[str, ...] = (
    "bybit",
    "binance",
    "okx",
    "kucoin",
    "garantex",
    "bitpapa",
    "huobi",
    "mexc",
    "bingx",
    "gate.io",
    "bitzlato",
    "crypto",
    "usdt",
    "btc",
    "eth",
    "p2p.binance",
    "p2p-бирж",
    "обменник",
    "exchange",
)

GAMBLING_KEYWORDS: tuple[str, ...] = (
    "casino",
    "1xbet",
    "fonbet",
    "betboom",
    "bet365",
    "pari",
    "ligastavok",
    "parimatch",
    "stake",
    "ставки",
    "букмекер",
)

BUSINESS_KEYWORDS: tuple[str, ...] = (
    "оплата услуг",
    "оплата товара",
    "за услуги",
    "за товар",
    "за работу",
    "по договору",
    "выполнение работ",
    "предоплата",
    "аванс",
    "закуп",
    "поставк",
    "счёт",
    "счет №",
)

SALARY_KEYWORDS: tuple[str, ...] = (
    "зарплата",
    "заработная плата",
    "аванс по зп",
    "оплата труда",
    "премия",
    "бонус",
    "выплата дохода",
)

# «Жизнеобеспечение»: ЖКХ, связь, маркетплейсы, АЗС, аптеки, продукты.
# Отсутствие таких платежей — сильный признак МР 16-МР (п.8).
LIFESTYLE_KEYWORDS: tuple[str, ...] = (
    "жкх",
    "коммунальн",
    "мосэнерго",
    "мосэнергосбыт",
    "газпром межрегионгаз",
    "водоканал",
    "теплосеть",
    "мтс",
    "beeline",
    "билайн",
    "мегафон",
    "tele2",
    "теле2",
    "ростелеком",
    "wildberries",
    "wb",
    "озон",
    "ozon",
    "яндекс.маркет",
    "яндекс маркет",
    "яндекс.еда",
    "самокат",
    "лавка",
    "перекрест",
    "магнит",
    "пятёрочка",
    "пятерочка",
    "ашан",
    "вкусвилл",
    "лукойл",
    "роснефть",
    "shell",
    "газпромнефть",
    "аптека",
    "ригла",
    "36.6",
    "подписка",
    "netflix",
    "youtube",
    "iphones",
    "ivi",
    "kinopoisk",
    "школа",
    "детский сад",
)

# Маркеры «взнос наличных через кассу / банкомат» — для МР 11-МР 2025.
CASH_DEPOSIT_KEYWORDS: tuple[str, ...] = (
    "внесение наличных",
    "взнос наличных",
    "взнос",
    "пополнение наличными",
    "пополнение через банкомат",
    "пополнение через кассу",
    "cash in",
    "cashin",
)

# Маркеры переводов на ИП / самозанятых (Сбер кейс 13.08.2025)
SELF_EMPLOYED_KEYWORDS: tuple[str, ...] = (
    "ип ",
    "ип.",
    "индивидуальный предприниматель",
    "самозанятому",
    "самозанятый",
    "нпд",
    "мой налог",
)

# Банки/СБП — помогает распознать «сразу вывел в другой банк».
EXTERNAL_BANK_HINTS: tuple[str, ...] = (
    "сбп",
    "перевод в другой банк",
    "перевод сбп",
    "перевод по номеру телефона",
    "внешний перевод",
)


# ----------------------------- пороги ----------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Настраиваемые пороги rule-based движка.

    Все значения по умолчанию соответствуют обычному режиму.
    Для "режима максимальной защиты" применяется :func:`tighten` — пороги
    уменьшаются, чтобы ловить даже пограничные паттерны.
    """

    # P2P-активность
    p2p_per_day_yellow: int = 10
    p2p_per_day_red: int = 20
    p2p_30d_yellow: int = 50
    p2p_30d_red: int = 100
    p2p_unique_counterparties_yellow: int = 30
    p2p_unique_counterparties_red: int = 60

    # Транзитность / mule-поведение
    transit_residual_ratio_yellow: float = 0.15  # доля, оставшаяся в конце дня
    transit_residual_ratio_red: float = 0.05
    same_day_turnover_share_yellow: float = 0.5
    same_day_turnover_share_red: float = 0.8

    # Крупные поступления
    large_income_rub_yellow: float = 300_000.0
    large_income_rub_red: float = 600_000.0
    total_monthly_turnover_yellow: float = 600_000.0
    total_monthly_turnover_red: float = 1_000_000.0

    # Мелкие частые операции (терминал / business-like)
    small_tx_count_day_yellow: int = 30
    small_tx_count_day_red: int = 60
    small_tx_amount_rub: float = 3_000.0

    # Наличные
    cash_ratio_yellow: float = 0.3
    cash_ratio_red: float = 0.5

    # Крипта / букмекеры
    crypto_ops_count_yellow: int = 3
    crypto_ops_count_red: int = 10

    # Бизнес-паттерн
    business_incoming_unique_counterparties_yellow: int = 10
    business_incoming_unique_counterparties_red: int = 25

    # Всплеск оборота
    turnover_spike_ratio_yellow: float = 3.0
    turnover_spike_ratio_red: float = 6.0

    # Пересечение с 161-ФЗ (новые карты / устройства)
    new_counterparty_share_yellow: float = 0.4
    new_counterparty_share_red: float = 0.7

    # -------------------- дополнения из реальных кейсов 2025–2026 --------------------
    # Быстрый in/out (МР 16-МР п.4: «менее минуты между зачислением и списанием»).
    fast_inout_share_yellow: float = 0.15
    fast_inout_share_red: float = 0.35
    fast_inout_window_seconds: int = 120

    # «Нет жизнеобеспечения» — отсутствуют платежи ЖКХ/связь/маркетплейсы (МР 16-МР п.8).
    no_lifestyle_days_yellow: int = 21
    no_lifestyle_days_red: int = 45

    # Круглосуточная активность (нетипична для физлица).
    round_clock_hours_yellow: int = 18
    round_clock_hours_red: int = 22

    # Комбо «крипта + букмекер» (кейс Сбер/Т-Банк — сразу в красную зону).
    crypto_gambling_combo_threshold: int = 3

    # P2P-вывод сразу после зачисления (Сбер кейс 17.02.2026: P2P крипта → СБП в другой банк).
    sbp_out_after_income_share_yellow: float = 0.4
    sbp_out_after_income_share_red: float = 0.7

    # Третьи лица вносят наличные на счёт (МР 11-МР от 09.09.2025).
    third_party_cash_deposits_yellow: int = 3
    third_party_cash_deposits_red: int = 8

    # Массовые переводы в сторону ИП/самозанятых (Сбер кейс 13.08.2025).
    ip_samozanyat_transfers_yellow: int = 10
    ip_samozanyat_transfers_red: int = 25

    # «Сбор/копилка» (кейс Т-Банк, 25.02.2026) — много входящих за 1–3 дня от разных колллег.
    collective_fundraising_unique_yellow: int = 8
    collective_fundraising_unique_red: int = 20
    collective_fundraising_window_days: int = 3

    # Доля поступлений от новых (неизвестных ранее) отправителей.
    new_senders_share_yellow: float = 0.5
    new_senders_share_red: float = 0.8

    # ----------------------- служебное -----------------------
    def tighten(self, factor: float = 0.7) -> Thresholds:
        """Вернуть более консервативные пороги для "Режима максимальной защиты".

        Args:
            factor: множитель для числовых порогов (меньше 1.0 — строже).
        """
        return Thresholds(
            p2p_per_day_yellow=max(1, int(self.p2p_per_day_yellow * factor)),
            p2p_per_day_red=max(2, int(self.p2p_per_day_red * factor)),
            p2p_30d_yellow=max(5, int(self.p2p_30d_yellow * factor)),
            p2p_30d_red=max(10, int(self.p2p_30d_red * factor)),
            p2p_unique_counterparties_yellow=max(5, int(self.p2p_unique_counterparties_yellow * factor)),
            p2p_unique_counterparties_red=max(10, int(self.p2p_unique_counterparties_red * factor)),
            transit_residual_ratio_yellow=self.transit_residual_ratio_yellow / factor,
            transit_residual_ratio_red=self.transit_residual_ratio_red / factor,
            same_day_turnover_share_yellow=min(1.0, self.same_day_turnover_share_yellow * factor),
            same_day_turnover_share_red=min(1.0, self.same_day_turnover_share_red * factor),
            large_income_rub_yellow=self.large_income_rub_yellow * factor,
            large_income_rub_red=self.large_income_rub_red * factor,
            total_monthly_turnover_yellow=self.total_monthly_turnover_yellow * factor,
            total_monthly_turnover_red=self.total_monthly_turnover_red * factor,
            small_tx_count_day_yellow=max(5, int(self.small_tx_count_day_yellow * factor)),
            small_tx_count_day_red=max(10, int(self.small_tx_count_day_red * factor)),
            small_tx_amount_rub=self.small_tx_amount_rub,
            cash_ratio_yellow=max(0.05, self.cash_ratio_yellow * factor),
            cash_ratio_red=max(0.1, self.cash_ratio_red * factor),
            crypto_ops_count_yellow=max(1, int(self.crypto_ops_count_yellow * factor)),
            crypto_ops_count_red=max(2, int(self.crypto_ops_count_red * factor)),
            business_incoming_unique_counterparties_yellow=max(
                3, int(self.business_incoming_unique_counterparties_yellow * factor)
            ),
            business_incoming_unique_counterparties_red=max(
                5, int(self.business_incoming_unique_counterparties_red * factor)
            ),
            turnover_spike_ratio_yellow=self.turnover_spike_ratio_yellow * factor,
            turnover_spike_ratio_red=self.turnover_spike_ratio_red * factor,
            new_counterparty_share_yellow=max(0.1, self.new_counterparty_share_yellow * factor),
            new_counterparty_share_red=max(0.2, self.new_counterparty_share_red * factor),
            fast_inout_share_yellow=max(0.05, self.fast_inout_share_yellow * factor),
            fast_inout_share_red=max(0.1, self.fast_inout_share_red * factor),
            fast_inout_window_seconds=self.fast_inout_window_seconds,
            no_lifestyle_days_yellow=max(7, int(self.no_lifestyle_days_yellow * factor)),
            no_lifestyle_days_red=max(14, int(self.no_lifestyle_days_red * factor)),
            round_clock_hours_yellow=max(10, int(self.round_clock_hours_yellow * factor)),
            round_clock_hours_red=max(12, int(self.round_clock_hours_red * factor)),
            crypto_gambling_combo_threshold=max(1, int(self.crypto_gambling_combo_threshold * factor)),
            sbp_out_after_income_share_yellow=max(0.1, self.sbp_out_after_income_share_yellow * factor),
            sbp_out_after_income_share_red=max(0.2, self.sbp_out_after_income_share_red * factor),
            third_party_cash_deposits_yellow=max(1, int(self.third_party_cash_deposits_yellow * factor)),
            third_party_cash_deposits_red=max(2, int(self.third_party_cash_deposits_red * factor)),
            ip_samozanyat_transfers_yellow=max(3, int(self.ip_samozanyat_transfers_yellow * factor)),
            ip_samozanyat_transfers_red=max(5, int(self.ip_samozanyat_transfers_red * factor)),
            collective_fundraising_unique_yellow=max(3, int(self.collective_fundraising_unique_yellow * factor)),
            collective_fundraising_unique_red=max(5, int(self.collective_fundraising_unique_red * factor)),
            collective_fundraising_window_days=self.collective_fundraising_window_days,
            new_senders_share_yellow=max(0.2, self.new_senders_share_yellow * factor),
            new_senders_share_red=max(0.3, self.new_senders_share_red * factor),
        )


DEFAULT_THRESHOLDS = Thresholds()


# ----------------------------- правила / флаги --------------------------


@dataclass(frozen=True)
class RuleSpec:
    """Описание одного правила/флага риска.

    Attributes:
        id:       Стабильный машинный идентификатор правила.
        name:     Короткое название для UI.
        category: Категория для группировки в отчёте.
        weight:   Базовый вес (0..100) при срабатывании в "красной" зоне.
        law:      Нормативная привязка (115-ФЗ / 161-ФЗ / МР ЦБ).
        why_dangerous: Объяснение "почему это опасно" для пользователя.
        action_hint:   Что делать прямо сейчас, чтобы снизить риск.
        case_reference: Ссылка-подсказка на типовой кейс (banki.ru / ЦБ).
    """

    id: str
    name: str
    category: str
    weight: float
    law: str
    why_dangerous: str
    action_hint: str
    case_reference: str = ""


# Каталог правил — источник правды для risk_engine и отчёта.
RULES: dict[str, RuleSpec] = {
    "p2p_daily_spike": RuleSpec(
        id="p2p_daily_spike",
        name="Высокая частота P2P-переводов в день",
        category="P2P-активность",
        weight=18.0,
        law="115-ФЗ · МР ЦБ 16-МР",
        why_dangerous=(
            "ЦБ в методических рекомендациях 16-МР прямо указал банкам отслеживать "
            "физлиц, у которых >10 P2P в сутки: это признак платёжного агента / дропа. "
            "На banki.ru с 2024 года сотни жалоб на блокировки именно по этому признаку."
        ),
        action_hint=(
            "Растяните переводы во времени, объединяйте платежи, используйте СБП "
            "на одного получателя вместо серии мелких, не принимайте деньги от чужих."
        ),
        case_reference="banki.ru/services/responses — тема «блокировка по 115-ФЗ за частые P2P»",
    ),
    "p2p_monthly_volume": RuleSpec(
        id="p2p_monthly_volume",
        name="Много P2P-переводов за 30 дней",
        category="P2P-активность",
        weight=14.0,
        law="115-ФЗ · МР ЦБ 16-МР (пороги от 08.2024)",
        why_dangerous=(
            "С 25.07.2024 ЦБ рекомендовал банкам обращать внимание на счета, где "
            ">100 операций и >50 контрагентов физлиц за месяц. По данным banki.ru "
            "именно этот критерий стал массовой причиной блокировок в 2025–2026."
        ),
        action_hint=(
            "Сократите количество встречных P2P, часть регулярных платежей переведите "
            "на свою же вторую карту, оформите самозанятость, если принимаете деньги "
            "за услуги."
        ),
        case_reference="ЦБ РФ, МР 16-МР от 2024-07-25",
    ),
    "transit_activity": RuleSpec(
        id="transit_activity",
        name="Транзитные операции (деньги не задерживаются)",
        category="Транзит и mule",
        weight=22.0,
        law="115-ФЗ · Положение 375-П п.5",
        why_dangerous=(
            "Если средства в тот же день уходят со счёта почти в полном объёме — "
            "это классический признак дропа/транзита. Положение 375-П прямо относит "
            "это к критериям подозрительности. Почти 100% блокировок в топике "
            "«заблокировали по 115-ФЗ» на banki.ru имеют этот паттерн."
        ),
        action_hint=(
            "Оставляйте на счёте реальный остаток, не пропускайте через себя чужие "
            "деньги, не участвуйте в «прокрутке» даже за комиссию — это уголовно."
        ),
        case_reference="Положение ЦБ № 375-П, МР 18-МР",
    ),
    "large_unexplained_income": RuleSpec(
        id="large_unexplained_income",
        name="Крупное необъяснимое поступление",
        category="Крупные операции",
        weight=12.0,
        law="115-ФЗ · 519-П",
        why_dangerous=(
            "Разовые поступления >300–600 тыс. ₽ без явного основания (зарплата, "
            "продажа имущества, возврат долга с документами) банк обязан проверить. "
            "На практике такие операции чаще всего заканчиваются блокировкой онлайн-"
            "банка и запросом документов по 115-ФЗ ст.7 п.14."
        ),
        action_hint=(
            "Заранее подготовьте подтверждающие документы (договор купли-продажи, "
            "расписка, договор займа, справка 2-НДФЛ). Оповестите банк о крупном "
            "поступлении заранее через чат."
        ),
        case_reference="banki.ru — «запросили документы по крупному переводу»",
    ),
    "micro_tx_flood": RuleSpec(
        id="micro_tx_flood",
        name="Много мелких частых переводов (паттерн терминала)",
        category="Бизнес-паттерн",
        weight=13.0,
        law="115-ФЗ · МР 17-МР",
        why_dangerous=(
            "Десятки мелких поступлений по 500–2 000 ₽ — паттерн нелегального "
            "торгового эквайринга: вы принимаете оплату вместо ИП. Банки "
            "автоматически выделяют такие счета с 2025 года."
        ),
        action_hint=(
            "Оформите самозанятость (НПД) или ИП — это снимает большинство вопросов. "
            "Для клиентов подключите СБП-QR через самозанятость."
        ),
        case_reference="banki.ru — «карта вместо терминала, 115-ФЗ»",
    ),
    "hidden_business": RuleSpec(
        id="hidden_business",
        name="Скрытая предпринимательская деятельность",
        category="Бизнес-паттерн",
        weight=16.0,
        law="115-ФЗ · ст.23 ГК РФ · 422-ФЗ",
        why_dangerous=(
            "Регулярные входящие переводы от множества разных физлиц с назначением "
            "«за услугу/товар/работу» при отсутствии статуса ИП/самозанятого — прямое "
            "основание для банка запросить документы и приостановить операции."
        ),
        action_hint=(
            "Зарегистрируйте самозанятость (это 3 минуты в приложении «Мой налог») "
            "и просите клиентов указывать назначение перевода нейтрально "
            "(«перевод», «возврат долга»), а основной доход проводить через НПД."
        ),
        case_reference="banki.ru — «получал за услуги, заблокировали 115-ФЗ»",
    ),
    "crypto_exchange": RuleSpec(
        id="crypto_exchange",
        name="Операции с крипто-обменниками и P2P-площадками",
        category="Крипта и обменники",
        weight=20.0,
        law="115-ФЗ · 161-ФЗ ст.8 · Письмо ЦБ ИН-017-45",
        why_dangerous=(
            "С 2024 банки помечают контрагентов, связанных с криптообменом "
            "(Bybit, Garantex, Bitpapa, P2P Binance). Попадание в цепочку с таким "
            "контрагентом автоматически переводит клиента в «высокий уровень риска» "
            "и часто — в отказ от обслуживания."
        ),
        action_hint=(
            "Не используйте основную зарплатную карту для P2P-обмена криптовалют. "
            "Крипта де-факто не запрещена, но для обмена лучше отдельный счёт / "
            "другой банк, и точно не с зарплатой в одном месте."
        ),
        case_reference="banki.ru — топики «блокировка после P2P Binance»",
    ),
    "high_cash_ratio": RuleSpec(
        id="high_cash_ratio",
        name="Высокий % наличных операций",
        category="Наличные",
        weight=10.0,
        law="115-ФЗ · МР 19-МР",
        why_dangerous=(
            "Снятие / внесение наличных на >30–50% от оборота — классический триггер. "
            "Особенно опасно чередование «пришёл безнал → снял наличку → внёс в другом "
            "банке»: это прямо описано в МР 19-МР."
        ),
        action_hint=(
            "Переводите меньше в наличные, используйте безнал для покупок. "
            "Если кэш необходим — снимайте реже и крупнее, а не мелко и часто."
        ),
        case_reference="МР ЦБ 19-МР",
    ),
    "turnover_spike": RuleSpec(
        id="turnover_spike",
        name="Резкий всплеск оборота",
        category="Динамика",
        weight=11.0,
        law="115-ФЗ · 519-П",
        why_dangerous=(
            "Резкий рост оборота в 3–6 раз относительно привычного — один из "
            "ключевых триггеров антифрод-моделей банков. На banki.ru типичный "
            "кейс: «получил возврат налога / продал авто — банк заблокировал»."
        ),
        action_hint=(
            "При крупной разовой операции — заранее напишите в чат банка и "
            "приложите документы. Это штатный сценарий, банк снимает ограничение "
            "за 1–2 рабочих дня."
        ),
        case_reference="banki.ru — «продал машину, заблокировали»",
    ),
    "fraud_overlap_161": RuleSpec(
        id="fraud_overlap_161",
        name="Признаки пересечения с 161-ФЗ (дроп/мошенничество)",
        category="161-ФЗ / антифрод",
        weight=25.0,
        law="161-ФЗ (с 25.07.2024) · 115-ФЗ",
        why_dangerous=(
            "С лета 2024 банки обязаны отключать онлайн-банк при признаках, что "
            "счёт используется дропом: новые неизвестные контрагенты, ночные P2P, "
            "быстрые переводы мелких сумм. Попадание в базу ФинЦЕРТ закрывает доступ "
            "к дистанционным операциям во всех банках."
        ),
        action_hint=(
            "Не принимайте переводы «для знакомого», не отдавайте карту третьим "
            "лицам даже за «аренду». Если счёт уже попал в базу — через банк "
            "подать заявление в ФинЦЕРТ на исключение."
        ),
        case_reference="banki.ru — «попал в базу ФинЦЕРТ, 161-ФЗ»",
    ),
    "high_p2p_unique_counterparties": RuleSpec(
        id="high_p2p_unique_counterparties",
        name="Много уникальных P2P-контрагентов",
        category="P2P-активность",
        weight=12.0,
        law="115-ФЗ · МР 16-МР",
        why_dangerous=(
            "Более 30–60 разных физических лиц в качестве контрагентов за месяц — "
            "признак, прямо указанный в МР 16-МР. Для обычного физлица это аномалия."
        ),
        action_hint=(
            "Проанализируйте список контрагентов: если это клиенты — переведите "
            "на самозанятость. Если это возвраты / сборы — используйте общий счёт "
            "или СБП-QR."
        ),
        case_reference="ЦБ РФ МР 16-МР",
    ),
    "gambling_ops": RuleSpec(
        id="gambling_ops",
        name="Операции с букмекерами и онлайн-казино",
        category="Гэмблинг",
        weight=8.0,
        law="115-ФЗ · 244-ФЗ",
        why_dangerous=(
            "Частые операции в сторону букмекеров (особенно иностранных) — "
            "повышают риск-категорию. Нелегальные казино — прямой повод для 115-ФЗ."
        ),
        action_hint=(
            "Используйте только легальные ЦУПИС (fonbet, winline, pari, "
            "liga-stavok); избегайте ставок на иностранные площадки."
        ),
        case_reference="banki.ru — «часто пополнял букмекера, 115-ФЗ»",
    ),
    # ---------- правила, добавленные по результатам разбора banki.ru-кейсов 2025–2026 ----------
    "fast_in_out": RuleSpec(
        id="fast_in_out",
        name="Мгновенный вывод денег после поступления",
        category="Транзит и mule",
        weight=18.0,
        law="115-ФЗ · МР 16-МР п.4 · Положение 375-П",
        why_dangerous=(
            "МР 16-МР прямо относит к подозрительным операции, в которых между "
            "зачислением и последующим списанием проходит менее минуты. Такой "
            "паттерн автоматически отлавливают антифрод-модели Сбера и Т-Банка "
            "(кейс 17.02.2026 на banki.ru: P2P-крипта → СБП в другой банк → блок)."
        ),
        action_hint=(
            "Не выводите деньги в другой банк сразу после зачисления: сделайте "
            "паузу 1–2 часа, оставьте часть суммы на счёте, при крупных поступлениях "
            "заранее предупредите банк в чате."
        ),
        case_reference="banki.ru/services/responses/bank/response/11226299/ (Сбер, P2P-крипта, 2026)",
    ),
    "no_lifestyle_payments": RuleSpec(
        id="no_lifestyle_payments",
        name="Нет платежей за жизнеобеспечение",
        category="Поведение",
        weight=14.0,
        law="115-ФЗ · МР 16-МР п.8",
        why_dangerous=(
            "МР 16-МР: банку подозрителен счёт, по которому нет платежей в пользу "
            "ЮЛ/ИП для обеспечения жизнедеятельности (ЖКХ, связь, маркетплейсы, АЗС). "
            "Это маркер «дроп-счёта»: живой человек тратит деньги, а дропы — нет."
        ),
        action_hint=(
            "Оплачивайте регулярные бытовые расходы (подписки, связь, ЖКХ, покупки) "
            "с этой же карты — это быстрый способ показать, что счёт «живой»."
        ),
        case_reference="МР ЦБ 16-МР от 06.09.2021, критерий 8",
    ),
    "round_the_clock": RuleSpec(
        id="round_the_clock",
        name="Круглосуточная активность по счёту",
        category="Поведение",
        weight=10.0,
        law="115-ФЗ · МР 16-МР п.5",
        why_dangerous=(
            "МР 16-МР: «операции проводятся круглосуточно, в том числе в нерабочее "
            "время». Физлицо обычно активно в окне 10–12 часов в сутки; активность "
            "18+ часов — признак автоматизированного сценария / дропа."
        ),
        action_hint=(
            "Избегайте пакетных ночных операций. Если вынуждены — рассинхронизируйте "
            "их с дневной активностью."
        ),
        case_reference="МР ЦБ 16-МР, п.5",
    ),
    "crypto_gambling_combo": RuleSpec(
        id="crypto_gambling_combo",
        name="Комбо «крипта + букмекер» в одной выписке",
        category="Крипта и гэмблинг",
        weight=22.0,
        law="115-ФЗ · 161-ФЗ · МР 18-МР",
        why_dangerous=(
            "Кейс Сбербанка (banki.ru, 2026): клиент совмещал беттинг и продажу "
            "криптовалюты через P2P. Банк заблокировал карты и отказал в выдаче "
            "новых, ссылаясь на коммерческую тайну. Сочетание этих каналов "
            "автоматически переводит клиента в высокорисковую категорию."
        ),
        action_hint=(
            "Разведите крипту и ставки по разным банкам. С зарплатным банком — только "
            "обычные расходы; для беттинга — отдельный счёт в банке, лояльном к "
            "ЦУПИС (не в основном зарплатном)."
        ),
        case_reference="banki.ru/services/responses/bank/response/11226299/",
    ),
    "sbp_out_after_income": RuleSpec(
        id="sbp_out_after_income",
        name="СБП-перевод в другой банк сразу после зачисления",
        category="Транзит и mule",
        weight=16.0,
        law="115-ФЗ · 161-ФЗ",
        why_dangerous=(
            "Типичный mule-паттерн: пришло — сразу ушло в другой банк через СБП. "
            "По кейсу Т-Банка (2026) такой трансфер интерпретируется как попытка "
            "«спрятать» происхождение средств, даже если сумма небольшая."
        ),
        action_hint=(
            "Не используйте СБП как «сквозной канал». Планируйте перевод заранее, "
            "дайте средствам задержаться на счёте хотя бы на сутки."
        ),
        case_reference="iphones.ru/1364685 (обзор блокировок Т-Банка, 2026)",
    ),
    "third_party_cash_deposits": RuleSpec(
        id="third_party_cash_deposits",
        name="Наличные на счёт вносят третьи лица",
        category="Наличные",
        weight=15.0,
        law="115-ФЗ · МР 11-МР от 09.09.2025",
        why_dangerous=(
            "С 09.09.2025 (МР 11-МР) ЦБ прямо потребовал от банков обращать внимание "
            "на зачисления наличных третьими лицами, не связанными с клиентом. Эти "
            "кейсы массово блокируются у Сбера и Ozon Банка."
        ),
        action_hint=(
            "Не позволяйте третьим лицам вносить наличные на ваш счёт. Если средства "
            "нужно передать вам — пусть переводят безналом (СБП) с указанием "
            "назначения («возврат долга», «подарок»)."
        ),
        case_reference="consultant.ru/document/cons_doc_LAW_514463/ (МР ЦБ 11-МР 2025)",
    ),
    "ip_samozanyat_transfers": RuleSpec(
        id="ip_samozanyat_transfers",
        name="Регулярные переводы на ИП/самозанятых",
        category="P2P-активность",
        weight=8.0,
        law="115-ФЗ · 422-ФЗ",
        why_dangerous=(
            "Сбер (кейс 13.08.2025): массовые переводы с карты физлица на ИП и "
            "самозанятых без явного экономического основания блокируются. Это "
            "интерпретируется как оплата услуг в обход НДФЛ / легализация."
        ),
        action_hint=(
            "Для регулярных оплат услуг ИП/самозанятым указывайте нейтральное "
            "назначение («оплата услуг», «возврат долга»), сохраняйте чеки из "
            "приложения «Мой налог», не плодите мелкие частые переводы."
        ),
        case_reference="banki.ru/services/questions-answers/question/798260/ (Сбер, 2025)",
    ),
    "collective_fundraising": RuleSpec(
        id="collective_fundraising",
        name="Сбор/копилка от большого числа людей",
        category="Бизнес-паттерн",
        weight=10.0,
        law="115-ФЗ · МР 16-МР п.1",
        why_dangerous=(
            "Кейс Т-Банка 25.02.2026: клиент собрал «копилку на 8 марта» от коллег, "
            "получил блокировку и запрос документов за 3 месяца по всем операциям. "
            "Много мелких поступлений от разных физлиц в короткий период — "
            "автоматически подпадает под МР 16-МР."
        ),
        action_hint=(
            "Для сборов используйте специализированные сервисы (Тинькофф «Круги», "
            "Сбер «Кошелёк»), а не обычный P2P. Если уже собрали — сохраните список "
            "коллег и цель сбора, будет чем ответить банку."
        ),
        case_reference="banki.ru/services/questions-answers/question/1005546/ (Т-Банк, 02.2026)",
    ),
    "new_senders_dominance": RuleSpec(
        id="new_senders_dominance",
        name="Большинство поступлений — от новых, ранее неизвестных отправителей",
        category="161-ФЗ / антифрод",
        weight=12.0,
        law="161-ФЗ · МР 16-МР п.1",
        why_dangerous=(
            "С 25.07.2024 признаком 161-ФЗ является резкий рост доли поступлений от "
            "отправителей, с которыми у клиента раньше не было взаимодействия. Эту "
            "метрику банки считают на своей стороне и автоматически помечают «дропа»."
        ),
        action_hint=(
            "Старайтесь, чтобы большинство поступлений приходило от известных "
            "отправителей (работодатель, семья, регулярные клиенты). Новых "
            "отправителей проверяйте сами — не принимайте деньги «на хранение» "
            "от незнакомцев."
        ),
        case_reference="v2b.ru/2025/09/22/droppery-na-kontrole-u-tsb-...",
    ),
}
