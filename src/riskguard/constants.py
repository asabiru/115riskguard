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

# --------- добавлено во второй волне разбора banki.ru (2025–2026) ---------

# Трансграничные переводы: банки/кошельки СНГ и стран, куда массово
# уводятся деньги через СБП/криптообменники. Сбер, Т-Банк и ВТБ в 2025–2026
# массово блокируют операции даже при попытке личного перевода самому себе.
CROSS_BORDER_KEYWORDS: tuple[str, ...] = (
    "казахстан",
    "kaspi",
    "каспи",
    "halyk",
    "халык",
    "айыл банк",
    "ayil bank",
    "киргизстан",
    "кыргызстан",
    "узбекистан",
    "humo",
    "humo card",
    "uzcard",
    "узкард",
    "беларусь",
    "belarusbank",
    "беларусбанк",
    "армения",
    "ameriabank",
    "freedom finance",
    "фридом финанс",
    "грузия",
    "tbc bank",
    "georgia",
    "турция",
    "isbank",
    "ziraat",
    "зираат",
    "swift",
    "iban",
)

# Маркеры отказов/возвратов в описаниях — если их много, значит антифрод
# банка уже триггерится. В связке с 115-ФЗ это усиливает подозрение.
REJECT_KEYWORDS: tuple[str, ...] = (
    "отказ в операции",
    "операция отклонена",
    "возврат неуспешного перевода",
    "возврат средств по отклон",
    "ошибка списания",
    "ограничение",
    "лимит превышен",
    "заблокировано",
    "приостановлен",
    "fraud",
    "отменено банком",
)

# Маркеры «пластика» (реальный POS/онлайн-шопинг) — если их нет при
# активном обороте, счёт выглядит как дроп-счёт (МР 16-МР п.8).
CARD_PURCHASE_KEYWORDS: tuple[str, ...] = (
    "покупка",
    "оплата",
    "pos ",
    "pos-",
    "pos.",
    "pay ",
    "apple pay",
    "samsung pay",
    "google pay",
    "sberpay",
    "сберпэй",
    "tinkoff pay",
    "mir pay",
    "мир пэй",
    "торгов",
    "магазин",
    "аптек",
    "кафе",
    "ресторан",
    "такси",
    "uber",
    "яндекс.такси",
    "яндекс такси",
    "delivery",
    "яндекс.еда",
    "самокат",
    "ozon",
    "wildberries",
)

# Маркеры снятия наличных в банкомате (для правила «обнал сразу после
# зачисления»). Разделены от CASH_DEPOSIT_KEYWORDS, т.к. это исходящая нога.
CASH_WITHDRAWAL_KEYWORDS: tuple[str, ...] = (
    "снятие наличных",
    "выдача наличных",
    "снятие в банкомате",
    "atm ",
    "банкомат",
    "cash out",
    "cashout",
    "получение наличных",
)


# ------ третья волна: сигналы антифрод-систем и комплаенс-правил 2025–2026 ------

# NFC-банкоматы — 7-й признак ЦБ РФ (приказ ОД-2506 от 05.11.2025, действует
# с 01.01.2026). Операции с бесконтактным банкоматом теперь автоматически
# попадают в антифрод-мониторинг как потенциальный перевод под давлением.
NFC_ATM_KEYWORDS: tuple[str, ...] = (
    "nfc",
    "нфс",
    "nfc банкомат",
    "nfc-банкомат",
    "бесконтактн",
    "contactless",
    "бесконтактный банкомат",
    "tap & go",
    "tap and go",
)

# Маркеры «база дропперов» / ФинЦЕРТ / отказ по 161-ФЗ.
# Если в выписке такие строки уже есть — антифрод-модель банка вас уже
# передала в ФинЦЕРТ (база ведётся согласно Указанию ЦБ 6748-У).
DROPPERS_REGISTRY_KEYWORDS: tuple[str, ...] = (
    "финцерт",
    "fincert",
    "база мошеннических",
    "реестр мошенн",
    "признак мошенн",
    "161-фз",
    "получатель внесён в реестр",
    "получатель включён в базу",
    "подозрительный получатель",
    "возврат по приказу цб",
    "указание 6748-у",
)

# FATF high-risk и grey-list страны + классические «отмывочные» юрисдикции.
# Актуально на апрель 2026 (CIS-исключены, акцент на Дубай/Турция/Кипр/офшоры).
FATF_HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "иран",
    "iran",
    "корея",
    "north korea",
    "кндр",
    "dprk",
    "мьянма",
    "myanmar",
    "алжир",
    "венесуэла",
    "сирия",
    "syria",
    "британские виргинские",
    "bvi",
    "кайман",
    "cayman",
    "панама",
    "белиз",
    "сейшел",
    "кипр",
    "cyprus",
    "мальта",
    "оаэ",
    "дубай",
    "uae",
    "hong kong",
    "гонконг",
    "singapore",
    "сингапур",
)

# Злоупотребление назначениями «подарок/займ/возврат долга» — МР 4-МР ЦБ:
# часто используется как прикрытие для обхода 115-ФЗ при приёме «серых» денег.
GIFT_LOAN_KEYWORDS: tuple[str, ...] = (
    "подарок",
    "в подарок",
    "gift",
    "займ",
    "заём",
    "в долг",
    "возврат долга",
    "возврат займа",
    "материальная помощь",
    "матпомощь",
    "по дружеской",
    "дружеский перевод",
)

# Драгоценные металлы и ОМС. Положение ЦБ 375-П (редакция 2025) прямо
# указывает на эти операции как на необычные при покупке сразу после
# крупного поступления без хранения актива в банке.
PRECIOUS_METALS_KEYWORDS: tuple[str, ...] = (
    "золото",
    "серебро",
    "платина",
    "палладий",
    "драгоценн",
    "драгметалл",
    "омс ",
    "обезличенный металлический",
    "gold",
    "silver",
    "platinum",
    "palladium",
    "слиток",
    "bullion",
)

# Маркеры «перевод себе» / «между счетами». Классический layering-приём:
# деньги прогоняются через цепочку своих счетов в разных банках, чтобы
# оторвать их от исходной точки (FATF typologies, SAS AML scenarios).
SELF_TRANSFER_KEYWORDS: tuple[str, ...] = (
    "перевод себе",
    "между своими",
    "между счетами",
    "на свой счёт",
    "на свою карту",
    "self-transfer",
    "own account",
    "me2me",
    "m2m",
    "перевод клиенту банка собственнику",
)

# Маркеры внешних банков — нужны для детекта «перевод себе через несколько
# банков» (self-transfer fanout). Расширенный список с учётом БИК/SWIFT-кодов.
EXTERNAL_BANK_NAMES: tuple[str, ...] = (
    "сбербанк",
    "sberbank",
    "втб",
    "vtb",
    "альфа",
    "alfa",
    "тинькофф",
    "тбанк",
    "т-банк",
    "tinkoff",
    "газпромбанк",
    "gazprombank",
    "открытие",
    "райффайзен",
    "raiff",
    "росбанк",
    "rosbank",
    "почта банк",
    "ozon банк",
    "ozon bank",
    "яндекс банк",
    "yandex bank",
    "мтс банк",
    "mts bank",
    "мкб",
    "промсвязьбанк",
    "псб",
    "psb",
    "совкомбанк",
    "sovcom",
    "русский стандарт",
    "rsb",
    "уралсиб",
    "home credit",
    "хоум кредит",
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

    # -------------- вторая волна правил из banki.ru (2025–2026) --------------
    # Доля круглых сумм среди P2P-поступлений — маркер автоматизации.
    round_amounts_share_yellow: float = 0.4
    round_amounts_share_red: float = 0.7

    # Повторяющиеся одинаковые входящие суммы.
    identical_amount_repeats_yellow: int = 5
    identical_amount_repeats_red: int = 12

    # Доля дохода, уходящая в день/на следующий день (salary-drain).
    salary_day_drain_ratio_yellow: float = 0.7
    salary_day_drain_ratio_red: float = 0.9

    # Пауза без операций перед всплеском (дни).
    dormant_days_yellow: int = 30
    dormant_days_red: int = 60

    # «Веер» банков: входящие из разных внешних банков в течение N дней.
    multi_bank_fanout_yellow: int = 4
    multi_bank_fanout_red: int = 8
    multi_bank_fanout_window_days: int = 7

    # Трансграничные операции (СНГ/swift).
    cross_border_transfers_yellow: int = 2
    cross_border_transfers_red: int = 5

    # Очень низкий средний чек P2P.
    very_low_avg_amount_yellow: float = 2_500.0
    very_low_avg_amount_red: float = 1_500.0
    very_low_avg_amount_min_ops: int = 30

    # Доля дохода, снятого в банкомате в тот же день.
    atm_cashout_after_income_yellow: float = 0.4
    atm_cashout_after_income_red: float = 0.7

    # Доминирование одного отправителя во входящих.
    one_dominant_sender_yellow: float = 0.6
    one_dominant_sender_red: float = 0.85

    # Новая карта с большим оборотом за короткий период (<14 дней).
    new_card_burst_turnover_yellow: float = 300_000.0
    new_card_burst_turnover_red: float = 700_000.0
    new_card_burst_days_max: int = 14

    # Отказы/возвраты в описаниях.
    rejected_ops_count_yellow: int = 3
    rejected_ops_count_red: int = 8

    # Отсутствие «настоящего пластика» (POS/онлайн-покупок) при активном счёте.
    no_card_purchases_tx_threshold: int = 20

    # ---------- третья волна: антифрод-системы + комплаенс 2025–2026 ----------
    # Structuring: операции чуть ниже порога обязательного контроля 600k ₽
    # (ст.6 115-ФЗ) — классический признак FATF и SAS AML.
    structuring_sub_threshold_yellow: int = 2
    structuring_sub_threshold_red: int = 5
    structuring_lower_bound_rub: float = 580_000.0
    structuring_upper_bound_rub: float = 599_999.0
    structuring_upper_bound_mln: float = 999_999.0
    structuring_lower_bound_mln: float = 970_000.0

    # Smurfing: несколько переводов одному получателю за день (дробление СБП).
    # Классика FATF + правило ЦБ по обходу лимитов СБП 100k/сутки.
    smurfing_same_receiver_ops_yellow: int = 3
    smurfing_same_receiver_ops_red: int = 6
    smurfing_same_receiver_sum_yellow: float = 100_000.0
    smurfing_same_receiver_sum_red: float = 300_000.0

    # NFC-банкоматы (приказ ЦБ ОД-2506 от 05.11.2025, действует с 01.01.2026).
    nfc_atm_ops_yellow: int = 1
    nfc_atm_ops_red: int = 3

    # ФинЦЕРТ / база дропперов (Указание ЦБ 6748-У).
    droppers_registry_hits_yellow: int = 1
    droppers_registry_hits_red: int = 2

    # Юрлицо/ИП → физлицу регулярно, без зарплатной статьи (375-П 2025).
    le_to_individual_regular_yellow: int = 3
    le_to_individual_regular_red: int = 6

    # Покупка драгметаллов после поступления (375-П 2025).
    precious_metals_after_income_yellow: int = 1
    precious_metals_after_income_red: int = 3

    # FATF high-risk юрисдикции.
    fatf_transfers_yellow: int = 1
    fatf_transfers_red: int = 3

    # Злоупотребление «подарок/займ/возврат долга» (МР 4-МР).
    gift_loan_abuse_yellow: int = 3
    gift_loan_abuse_red: int = 8
    gift_loan_abuse_share_yellow: float = 0.2
    gift_loan_abuse_share_red: float = 0.4

    # Velocity: N+ операций в одну минуту (FICO Falcon velocity-rule).
    velocity_per_minute_yellow: int = 3
    velocity_per_minute_red: int = 6

    # Self-transfer fanout: переводы «себе» в разные банки (layering FATF).
    self_transfer_banks_yellow: int = 2
    self_transfer_banks_red: int = 4

    # Mirror transfers: взаимные P2P с одним контрагентом (тест layering).
    mirror_transfers_pairs_yellow: int = 3
    mirror_transfers_pairs_red: int = 8

    # СБП-split одному получателю (обход лимита 100k/сутки).
    sbp_split_same_receiver_yellow: int = 3
    sbp_split_same_receiver_red: int = 5
    sbp_split_window_hours: int = 24

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
            round_amounts_share_yellow=max(0.15, self.round_amounts_share_yellow * factor),
            round_amounts_share_red=max(0.3, self.round_amounts_share_red * factor),
            identical_amount_repeats_yellow=max(2, int(self.identical_amount_repeats_yellow * factor)),
            identical_amount_repeats_red=max(4, int(self.identical_amount_repeats_red * factor)),
            salary_day_drain_ratio_yellow=max(0.4, self.salary_day_drain_ratio_yellow * factor),
            salary_day_drain_ratio_red=max(0.6, self.salary_day_drain_ratio_red * factor),
            dormant_days_yellow=max(10, int(self.dormant_days_yellow * factor)),
            dormant_days_red=max(20, int(self.dormant_days_red * factor)),
            multi_bank_fanout_yellow=max(2, int(self.multi_bank_fanout_yellow * factor)),
            multi_bank_fanout_red=max(4, int(self.multi_bank_fanout_red * factor)),
            multi_bank_fanout_window_days=self.multi_bank_fanout_window_days,
            cross_border_transfers_yellow=max(1, int(self.cross_border_transfers_yellow * factor)),
            cross_border_transfers_red=max(2, int(self.cross_border_transfers_red * factor)),
            very_low_avg_amount_yellow=self.very_low_avg_amount_yellow / factor,
            very_low_avg_amount_red=self.very_low_avg_amount_red / factor,
            very_low_avg_amount_min_ops=max(10, int(self.very_low_avg_amount_min_ops * factor)),
            atm_cashout_after_income_yellow=max(0.15, self.atm_cashout_after_income_yellow * factor),
            atm_cashout_after_income_red=max(0.3, self.atm_cashout_after_income_red * factor),
            one_dominant_sender_yellow=max(0.3, self.one_dominant_sender_yellow * factor),
            one_dominant_sender_red=max(0.5, self.one_dominant_sender_red * factor),
            new_card_burst_turnover_yellow=self.new_card_burst_turnover_yellow * factor,
            new_card_burst_turnover_red=self.new_card_burst_turnover_red * factor,
            new_card_burst_days_max=self.new_card_burst_days_max,
            rejected_ops_count_yellow=max(1, int(self.rejected_ops_count_yellow * factor)),
            rejected_ops_count_red=max(2, int(self.rejected_ops_count_red * factor)),
            no_card_purchases_tx_threshold=max(5, int(self.no_card_purchases_tx_threshold * factor)),
            structuring_sub_threshold_yellow=max(1, int(self.structuring_sub_threshold_yellow * factor)),
            structuring_sub_threshold_red=max(2, int(self.structuring_sub_threshold_red * factor)),
            structuring_lower_bound_rub=self.structuring_lower_bound_rub * factor,
            structuring_upper_bound_rub=self.structuring_upper_bound_rub,
            structuring_upper_bound_mln=self.structuring_upper_bound_mln,
            structuring_lower_bound_mln=self.structuring_lower_bound_mln * factor,
            smurfing_same_receiver_ops_yellow=max(2, int(self.smurfing_same_receiver_ops_yellow * factor)),
            smurfing_same_receiver_ops_red=max(3, int(self.smurfing_same_receiver_ops_red * factor)),
            smurfing_same_receiver_sum_yellow=self.smurfing_same_receiver_sum_yellow * factor,
            smurfing_same_receiver_sum_red=self.smurfing_same_receiver_sum_red * factor,
            nfc_atm_ops_yellow=max(1, int(self.nfc_atm_ops_yellow * factor)),
            nfc_atm_ops_red=max(1, int(self.nfc_atm_ops_red * factor)),
            droppers_registry_hits_yellow=max(1, int(self.droppers_registry_hits_yellow * factor)),
            droppers_registry_hits_red=max(1, int(self.droppers_registry_hits_red * factor)),
            le_to_individual_regular_yellow=max(1, int(self.le_to_individual_regular_yellow * factor)),
            le_to_individual_regular_red=max(2, int(self.le_to_individual_regular_red * factor)),
            precious_metals_after_income_yellow=max(1, int(self.precious_metals_after_income_yellow * factor)),
            precious_metals_after_income_red=max(1, int(self.precious_metals_after_income_red * factor)),
            fatf_transfers_yellow=max(1, int(self.fatf_transfers_yellow * factor)),
            fatf_transfers_red=max(1, int(self.fatf_transfers_red * factor)),
            gift_loan_abuse_yellow=max(1, int(self.gift_loan_abuse_yellow * factor)),
            gift_loan_abuse_red=max(2, int(self.gift_loan_abuse_red * factor)),
            gift_loan_abuse_share_yellow=max(0.05, self.gift_loan_abuse_share_yellow * factor),
            gift_loan_abuse_share_red=max(0.1, self.gift_loan_abuse_share_red * factor),
            velocity_per_minute_yellow=max(2, int(self.velocity_per_minute_yellow * factor)),
            velocity_per_minute_red=max(3, int(self.velocity_per_minute_red * factor)),
            self_transfer_banks_yellow=max(1, int(self.self_transfer_banks_yellow * factor)),
            self_transfer_banks_red=max(2, int(self.self_transfer_banks_red * factor)),
            mirror_transfers_pairs_yellow=max(1, int(self.mirror_transfers_pairs_yellow * factor)),
            mirror_transfers_pairs_red=max(2, int(self.mirror_transfers_pairs_red * factor)),
            sbp_split_same_receiver_yellow=max(2, int(self.sbp_split_same_receiver_yellow * factor)),
            sbp_split_same_receiver_red=max(3, int(self.sbp_split_same_receiver_red * factor)),
            sbp_split_window_hours=self.sbp_split_window_hours,
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
    # ------------- вторая волна (разбор 100+ кейсов banki.ru 2025–2026) -------------
    "round_amounts_pattern": RuleSpec(
        id="round_amounts_pattern",
        name="Много «ровных» сумм во входящих переводах",
        category="Автоматизация / дроп",
        weight=10.0,
        law="115-ФЗ · МР 16-МР п.2 · Положение 375-П",
        why_dangerous=(
            "Поступления на «красивые» суммы (5 000, 10 000, 50 000 ₽) массово — "
            "явный признак автоматических отправок из «миксеров» или сайтов-обменников. "
            "Нормальные P2P у физлиц почти всегда «неровные» (ресторан/такси/долг)."
        ),
        action_hint=(
            "Если вы принимаете платежи за услуги — выставляйте счёт на конкретную "
            "сумму работы (1 247 ₽ за X часов), а не «чисто 5 000». Так банк видит "
            "живого клиента, а не автомат."
        ),
        case_reference="banki.ru — массовые 115-ФЗ-кейсы (Сбер/Т-Банк) 2025–2026",
    ),
    "identical_amount_repeats": RuleSpec(
        id="identical_amount_repeats",
        name="Многократные одинаковые входящие суммы",
        category="Автоматизация / дроп",
        weight=12.0,
        law="115-ФЗ · МР 16-МР п.2",
        why_dangerous=(
            "5+ одинаковых входящих сумм за короткий период — характерный "
            "паттерн дропов-«операторов»: им льют одинаковые «тики» с обменника "
            "или биржи. Описан в массовых кейсах Цифра Банка и Ozon Bank 2026."
        ),
        action_hint=(
            "Если это возвраты долгов — попросите друзей добавить копейки "
            "(«1 001 ₽» вместо «1 000 ₽») и писать осмысленное назначение платежа."
        ),
        case_reference="banki.ru/services/responses/bank/response/12957984/ (Ozon, 2026)",
    ),
    "salary_day_drain": RuleSpec(
        id="salary_day_drain",
        name="Весь доход уходит со счёта в день поступления",
        category="Транзит и mule",
        weight=15.0,
        law="115-ФЗ · МР 16-МР п.6 · 375-П",
        why_dangerous=(
            "Если больше 70 % всей зарплаты/входящих уходит на другие счета в тот же "
            "день — банк расценивает счёт как «перевалочный», а не как «счёт "
            "физлица для жизни». МР 16-МР прямо называет этот паттерн."
        ),
        action_hint=(
            "Оставляйте остаток хотя бы 10–20 % поступлений до конца дня. "
            "Если нужно переводить на другой банк — разнесите по времени "
            "(не в тот же час)."
        ),
        case_reference="banki.ru — «зарплата пришла → сразу на другой банк, блок»",
    ),
    "dormant_then_active": RuleSpec(
        id="dormant_then_active",
        name="Долгая пауза — а потом резкая активность",
        category="Компрометация / антифрод",
        weight=14.0,
        law="161-ФЗ · 115-ФЗ · 519-П",
        why_dangerous=(
            "Счёт не использовался 30+ дней, а затем пошли активные операции — "
            "классический сценарий компрометации карты или «аренды счёта». "
            "В кейсах 2026 Сбер массово блокирует такие счета и отказывает в "
            "перевыпуске карт."
        ),
        action_hint=(
            "Если реально долго не пользовались — сначала сделайте пару мелких "
            "операций (оплата ЖКХ, покупка в магазине), а уже потом крупные. "
            "Так антифрод увидит «живого» владельца."
        ),
        case_reference="banki.ru/services/responses/bank/response/11501829/ (Сбер 2026)",
    ),
    "multi_bank_fanout": RuleSpec(
        id="multi_bank_fanout",
        name="Веер входящих из разных банков за короткий период",
        category="Сбор / mule",
        weight=11.0,
        law="115-ФЗ · 161-ФЗ · МР 16-МР п.1",
        why_dangerous=(
            "Поступления через СБП из 5+ разных банков за неделю — паттерн "
            "«сбора»: либо неформальная касса, либо дроп-схема «клиенты заливают "
            "на один счёт со всех банков, владелец выводит». Массово ловится "
            "Т-Банком и Ozon Bank."
        ),
        action_hint=(
            "Если это настоящий сбор — используйте легальные инструменты "
            "(Т-Банк «Круги», Сбер «Кошелёк», платформы краудфандинга). Если "
            "бизнес — регистрируйте ИП/самозанятость."
        ),
        case_reference="banki.ru/services/questions-answers/question/1005546/",
    ),
    "cross_border_transfers": RuleSpec(
        id="cross_border_transfers",
        name="Переводы в/из стран ближнего зарубежья",
        category="Трансграничные операции",
        weight=9.0,
        law="115-ФЗ · 173-ФЗ (валютный контроль) · Указание 5474-У",
        why_dangerous=(
            "Переводы на/с карт Kaspi, Halyk, Айыл Банк, Freedom Finance и других "
            "банков СНГ — в 2025 одна из главных причин блокировок у Сбера, Т-Банка "
            "и ВТБ. Банк обязан применять усиленный контроль по 173-ФЗ."
        ),
        action_hint=(
            "Не переводите в банк СНГ прямо с зарплатной карты крупные суммы без "
            "документов. Используйте специализированные сервисы (Золотая Корона, "
            "KoronaPay) и готовьте обоснование (договор/инвойс/цель поездки)."
        ),
        case_reference="banki.ru/services/questions-answers/question/706958/ (Сбер, Айыл Банк)",
    ),
    "very_low_avg_amount": RuleSpec(
        id="very_low_avg_amount",
        name="Очень мелкий средний чек при большом числе операций",
        category="Микро-переводы",
        weight=10.0,
        law="115-ФЗ · МР 4-МР · МР 16-МР",
        why_dangerous=(
            "Десятки P2P-переводов со средним чеком < 1500 ₽ — признак нелегального "
            "терминала или «комнаты дропов»: мелкие тики с биржи ставок, "
            "обменника, беттинга."
        ),
        action_hint=(
            "Укрупняйте операции: вместо 30 мелких входящих — одно крупное. "
            "Если это реальные клиенты — подумайте про единую подписку/пакет."
        ),
        case_reference="banki.ru — кейсы нелегальных терминалов 2025",
    ),
    "atm_cashout_after_income": RuleSpec(
        id="atm_cashout_after_income",
        name="Снятие большей части дохода в банкомате в тот же день",
        category="Наличные",
        weight=12.0,
        law="115-ФЗ · МР 4-МР · МР 19-МР",
        why_dangerous=(
            "Если > 50 % поступлений в тот же день уходит через банкомат — "
            "классический обнал. МР 4-МР прямо описывает этот паттерн как "
            "«обналичивание доходов физлиц в интересах третьих лиц»."
        ),
        action_hint=(
            "Снимайте наличные реже и в один-два приёма, а не сразу после "
            "каждого зачисления. Основные траты — безналом."
        ),
        case_reference="banki.ru — Почта Банк/Газпромбанк блокировки при снятиях",
    ),
    "one_dominant_sender": RuleSpec(
        id="one_dominant_sender",
        name="Один отправитель даёт большинство поступлений",
        category="Скрытый бизнес / аренда",
        weight=10.0,
        law="115-ФЗ · ст.209 НК РФ · 422-ФЗ",
        why_dangerous=(
            "Когда >60 % всех поступлений — от одного и того же физ. контрагента "
            "с регулярной периодичностью (особенно ~30 дней), это характерно "
            "для неоформленной аренды жилья или «серой» зарплаты. Сбер в 2025–2026 "
            "массово запрашивает документы в таких случаях."
        ),
        action_hint=(
            "Оформите аренду через самозанятость и платите НПД 4 %. Тогда "
            "поступления получат статус официального дохода, и никаких "
            "блокировок не будет."
        ),
        case_reference="banki.ru — «аренда квартиры, блокировка по 115-ФЗ»",
    ),
    "new_card_burst": RuleSpec(
        id="new_card_burst",
        name="Свежевыпущенная карта и большой оборот",
        category="Антифрод / новые счета",
        weight=14.0,
        law="161-ФЗ · 115-ФЗ · 519-П",
        why_dangerous=(
            "Период наблюдения < 14 дней при обороте 300k+ ₽ — это «молодой» "
            "счёт с нехарактерным трафиком. В 2026 Яндекс Банк блокировал счета "
            "уже через 3 минуты после открытия, если обнаруживал такие признаки."
        ),
        action_hint=(
            "На новой карте первые 1–2 недели делайте обычные мелкие операции "
            "(покупка кофе, оплата связи), прежде чем запускать через неё "
            "крупные потоки."
        ),
        case_reference="banki.ru/services/responses/bank/response/12226201/ (Яндекс Банк, 2026)",
    ),
    "rejected_operations": RuleSpec(
        id="rejected_operations",
        name="Следы отказов и возвратов со стороны антифрода",
        category="Антифрод",
        weight=8.0,
        law="115-ФЗ · 161-ФЗ",
        why_dangerous=(
            "Если в выписке уже есть строки «отказ в операции / возврат неуспешного "
            "перевода / приостановлено» — антифрод-модель банка вас уже пометила. "
            "Следующий шаг обычно — блокировка всей карты."
        ),
        action_hint=(
            "Не пытайтесь «обойти» отказ, меняя сумму или канал. Напишите в чат "
            "банка, приложите документы по проблемным операциям, уточните причину."
        ),
        case_reference="banki.ru — массовые «Фрод-мониторинг блокирует перевод» (Сбер, Цифра Банк)",
    ),
    "no_card_purchases": RuleSpec(
        id="no_card_purchases",
        name="Нет настоящих POS/онлайн-покупок при активном счёте",
        category="Дроп-счёт",
        weight=13.0,
        law="115-ФЗ · МР 16-МР п.8",
        why_dangerous=(
            "При 20+ операциях за месяц ни одной реальной покупки (магазин/кафе/"
            "такси/онлайн) — прямой индикатор «дроп-счёта»: человек не живёт "
            "со счёта, а использует его только как транзит."
        ),
        action_hint=(
            "Проводите через счёт обычные бытовые расходы — кофе, такси, "
            "интернет-подписки. Это дёшево и радикально снижает «дроповость» "
            "профиля в глазах банка."
        ),
        case_reference="МР ЦБ 16-МР п.8; banki.ru — кейсы Т-Банк/Альфа 2025–2026",
    ),
    # ------- третья волна: антифрод-системы + комплаенс 2025–2026 -------
    "structuring_sub_threshold": RuleSpec(
        id="structuring_sub_threshold",
        name="Structuring: дробление под порогом обязательного контроля",
        category="AML / FATF",
        weight=20.0,
        law="115-ФЗ ст.6 · 375-П · FATF 40 Recommendations",
        why_dangerous=(
            "Операции на 580–599 тыс. или 970–999 тыс. ₽ идут ровно под "
            "порогом обязательного контроля (600k и 1M ₽). FICO Falcon, "
            "SAS AML и все российские комплаенс-системы (ЦФТ, BSS, КУС) "
            "ловят этот паттерн как классический FATF-structuring: "
            "клиент сознательно избегает автоматического отчёта в Росфинмониторинг."
        ),
        action_hint=(
            "Не дробите крупные суммы. Если операция реальная — лучше "
            "пропустить её выше порога и подготовить подтверждающие документы. "
            "Раздробленные операции намного подозрительнее, чем одна прозрачная."
        ),
        case_reference="FATF Typologies Report + ст.6 115-ФЗ (порог 600k/1M ₽)",
    ),
    "smurfing_same_receiver": RuleSpec(
        id="smurfing_same_receiver",
        name="Smurfing: дробление одному получателю в течение дня",
        category="AML / FATF",
        weight=16.0,
        law="115-ФЗ · МР 4-МР · FATF",
        why_dangerous=(
            "3+ перевода одному и тому же получателю за сутки на суммарные "
            "100k+ ₽ при среднем чеке <40k — классический smurfing. Банки "
            "видят это как попытку обойти лимит СБП 100k ₽/сутки и признак "
            "«оптового» канала (ставки, p2p-крипта, торговля товарами без регистрации)."
        ),
        action_hint=(
            "Делайте один перевод вместо нескольких. Если делите намеренно — "
            "скорее всего, вы уже нарушаете лимит СБП и попадаете в "
            "автоматический антифрод-сценарий."
        ),
        case_reference="FATF smurfing typology · banki.ru — массовые СБП-блокировки 2025–2026",
    ),
    "nfc_atm_ops": RuleSpec(
        id="nfc_atm_ops",
        name="Операции с NFC-банкоматом (новый признак ЦБ 2026)",
        category="Антифрод / 161-ФЗ",
        weight=18.0,
        law="161-ФЗ · Приказ ЦБ ОД-2506 от 05.11.2025",
        why_dangerous=(
            "С 01.01.2026 операции с бесконтактными (NFC) банкоматами включены "
            "в обязательный список антифрод-признаков ЦБ РФ (ОД-2506, п.7). "
            "Схема «снятие под давлением по NFC через QR» стала массовой в "
            "конце 2025 — теперь каждая такая операция проходит усиленный контроль."
        ),
        action_hint=(
            "При снятии крупных сумм используйте обычный банкомат с картой. "
            "NFC/бесконтактное снятие без реальной необходимости лучше не "
            "делать — это автоматически повышает фрод-скор операции."
        ),
        case_reference="cbr.ru — Приказ ОД-2506 от 05.11.2025 (действует с 01.01.2026)",
    ),
    "droppers_registry": RuleSpec(
        id="droppers_registry",
        name="Следы реестра дропперов ФинЦЕРТ в выписке",
        category="Антифрод / 161-ФЗ",
        weight=25.0,
        law="161-ФЗ · Указание ЦБ 6748-У · ФинЦЕРТ",
        why_dangerous=(
            "Строки «возврат по 161-ФЗ / получатель внесён в реестр / ФинЦЕРТ / "
            "признак мошеннической операции» — это прямой признак, что банк "
            "уже остановил операцию по базе дропперов. Следующий шаг почти "
            "всегда — приостановка карты или полный блок по 115-ФЗ."
        ),
        action_hint=(
            "Срочно — в банк, лично или через чат: объяснить источник денег, "
            "получить выписку и, если вы не дроппер, подать заявление на исключение "
            "из базы (порядок обновлён Указанием 7287-У, действует с 02.05.2026)."
        ),
        case_reference="cbr.ru · ФинЦЕРТ + garant.ru — новый порядок исключения из базы дропперов",
    ),
    "le_to_individual_regular": RuleSpec(
        id="le_to_individual_regular",
        name="Регулярные переводы от юрлиц/ИП физлицу (не зарплата)",
        category="Скрытый бизнес",
        weight=13.0,
        law="115-ФЗ · Положение 375-П (ред. 2025) · 422-ФЗ",
        why_dangerous=(
            "В обновлённом 375-П (февраль 2025) ЦБ прямо указал: регулярные "
            "переводы от ЮЛ/ИП в адрес гражданина, если это не кредит, зарплата "
            "или иные вознаграждения, — признак подозрительной операции. "
            "Типичный кейс: «серые» выплаты гонораров или обналичивание через "
            "зицпарт-ИП."
        ),
        action_hint=(
            "Оформите отношения через самозанятость (422-ФЗ, НПД 4 %/6 %) или "
            "трудовой договор. В назначении платежа должна быть чёткая ссылка "
            "на договор и услугу."
        ),
        case_reference="ruslom.com — обновление 375-П 2025 · ЦБ РФ письмо от 18.02.2025",
    ),
    "precious_metals_after_income": RuleSpec(
        id="precious_metals_after_income",
        name="Покупка драгметаллов сразу после крупного поступления",
        category="AML / 375-П",
        weight=14.0,
        law="115-ФЗ · Положение 375-П (ред. 2025)",
        why_dangerous=(
            "Положение 375-П в редакции 2025 выделяет в отдельный класс: "
            "покупку драгметаллов/слитков/ОМС сразу после поступления крупных "
            "средств без хранения актива в банке. Это классическая схема "
            "«placement → integration» по FATF."
        ),
        action_hint=(
            "Если покупка металлов реальная и для сбережений — открывайте ОМС "
            "в том же банке (актив остаётся внутри периметра) и не выводите "
            "сразу после зачисления. Разнесите операции во времени."
        ),
        case_reference="ruslom.com / hflabs.ru — 375-П редакция 2025, драгметаллы",
    ),
    "fatf_high_risk_transfers": RuleSpec(
        id="fatf_high_risk_transfers",
        name="Переводы в юрисдикции высокого риска FATF",
        category="AML / Санкции",
        weight=18.0,
        law="115-ФЗ · FATF High-Risk Jurisdictions · 173-ФЗ",
        why_dangerous=(
            "Операции в адрес Ирана, КНДР, Мьянмы, Сирии, офшоров (BVI/Кайманы/"
            "Панама/Кипр/Белиз/Сейшелы), а также Дубая/Гонконга/Сингапура "
            "автоматически попадают под усиленный контроль. Даже если вы "
            "просто помогаете родственнику — банк требует документы и "
            "блокирует до прояснения."
        ),
        action_hint=(
            "Заранее подготовьте: назначение платежа, документы (договор, счёт, "
            "билет), документы о происхождении средств. По возможности, "
            "проводите такие платежи через валютный контроль банка."
        ),
        case_reference="FATF High-Risk and Other Monitored Jurisdictions (актуальный список)",
    ),
    "gift_loan_abuse": RuleSpec(
        id="gift_loan_abuse",
        name="Злоупотребление назначениями «подарок / займ / возврат долга»",
        category="Скрытый бизнес · МР 4-МР",
        weight=10.0,
        law="115-ФЗ · МР ЦБ 4-МР",
        why_dangerous=(
            "МР 4-МР прямо называет это типовым сценарием прикрытия. Если "
            "20–40 % входящих P2P идут с назначением «подарок» или «возврат "
            "долга» от разных людей — банк считает, что вы принимаете оплату "
            "за товар/услугу, избегая налогов и статуса предпринимателя."
        ),
        action_hint=(
            "Попросите отправителей писать реальное и осмысленное назначение. "
            "Если это оплата за услугу — оформите самозанятость. «Подарок» "
            "от нескольких разных людей каждую неделю — самый тревожный маркер."
        ),
        case_reference="МР ЦБ 4-МР · banki.ru — Сбер/Т-Банк кейсы «подарок, 115-ФЗ»",
    ),
    "velocity_per_minute": RuleSpec(
        id="velocity_per_minute",
        name="Всплеск velocity: несколько операций в одну минуту",
        category="Антифрод / бот",
        weight=12.0,
        law="161-ФЗ · FICO Falcon velocity-rule",
        why_dangerous=(
            "Базовое правило FICO Falcon, SAS AML и ЦФТ Антифрод: человек не "
            "совершает 3–6 разных операций в одну минуту. Такой всплеск "
            "срабатывает на автоматизацию (скрипт / бот / массовая рассылка "
            "СБП) и на перехват сессии мошенниками."
        ),
        action_hint=(
            "Если это были реальные операции — растягивайте во времени (хотя "
            "бы 10–15 сек между кликами). Если нет — срочно смените пароль и "
            "проверьте устройства, на которых авторизован онлайн-банк."
        ),
        case_reference="FICO Falcon Fraud Manager · ЦФТ Антифрод velocity-сценарий",
    ),
    "self_transfer_multi_banks": RuleSpec(
        id="self_transfer_multi_banks",
        name="Layering: переводы «себе» между разными банками",
        category="AML / FATF layering",
        weight=14.0,
        law="115-ФЗ · FATF typologies · МР 16-МР",
        why_dangerous=(
            "Переводы «на свой счёт» в 3+ разных банка — классический "
            "layering по FATF. Даже если деньги ваши, многократная пересылка "
            "между банками «для дешевизны» выглядит как попытка оторвать "
            "средства от исходной точки. SAS AML и BSS Fraud-Анализ ловят "
            "это как отдельный сценарий."
        ),
        action_hint=(
            "Сократите количество «прокладочных» банков. Держите один "
            "основной счёт для накоплений, другой — для повседневных операций."
        ),
        case_reference="FATF Methods and Trends · SAS AML scenario «self-transfer chain»",
    ),
    "mirror_transfers_counterparty": RuleSpec(
        id="mirror_transfers_counterparty",
        name="Зеркальные P2P (туда-сюда) с одним контрагентом",
        category="AML / FATF layering",
        weight=12.0,
        law="115-ФЗ · МР 4-МР · FATF",
        why_dangerous=(
            "Взаимные переводы с одним и тем же контрагентом (входящий и "
            "исходящий в близкой сумме) — признак «прогона денег»: маскировки "
            "источника, теста антифрода перед крупной транзакцией или "
            "расчёта за крипту на P2P-биржах."
        ),
        action_hint=(
            "Избегайте перекрёстных переводов с одним и тем же человеком. "
            "Если это семейные расчёты — объединяйте в один перевод с "
            "осмысленным назначением."
        ),
        case_reference="МР 4-МР · banki.ru — кейсы «P2P-Binance, возврат 115-ФЗ»",
    ),
    "sbp_split_same_receiver": RuleSpec(
        id="sbp_split_same_receiver",
        name="Дробление СБП одному получателю (обход лимита 100k ₽/сутки)",
        category="Антифрод / СБП",
        weight=14.0,
        law="115-ФЗ · 161-ФЗ · Правила СБП",
        why_dangerous=(
            "Лимит СБП для бесплатных переводов — 100k ₽/сутки на получателя. "
            "Дробление на 3–5 переводов в один день по одному номеру телефона "
            "трактуется антифродом как сознательный обход лимита и признак "
            "«серой» оптовой активности (ставки, продажа крипты, товары "
            "без регистрации)."
        ),
        action_hint=(
            "Если нужна сумма >100k ₽ — используйте межбанковский перевод по "
            "реквизитам или СБП-платёж с комиссией. Не дробите."
        ),
        case_reference="Правила СБП · banki.ru — массовые блокировки 2025–2026",
    ),
}
