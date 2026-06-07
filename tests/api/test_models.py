"""Tests unitaires des modèles de données EasyCare (api/models.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from custom_components.easycare_bywaterair.api.exceptions import EasyCareInvalidResponseError
from custom_components.easycare_bywaterair.api.models import (
    Alerts,
    BPCInput,
    BearerToken,
    Client,
    CyclicRule,
    FilterSchedule,
    Metrics,
    Module,
    ModuleOutput,
    Notification,
    OAuthTokens,
    Pool,
    PoolStatus,
    Treatment,
    _parse_timestamp,
)

FAKE_NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# OAuthTokens
# ---------------------------------------------------------------------------

class TestOAuthTokens:
    def test_from_api_nominal(self):
        data = {
            "id_token": "id-tok",
            "refresh_token": "ref-tok",
            "access_token": "acc-tok",
            "expires_in": 3600,
        }
        tokens = OAuthTokens.from_api(data, now=FAKE_NOW)
        assert tokens.id_token == "id-tok"
        assert tokens.refresh_token == "ref-tok"
        assert tokens.access_token == "acc-tok"
        assert tokens.expires_at == FAKE_NOW + 3600

    def test_from_api_missing_id_token_raises(self):
        data = {"refresh_token": "ref"}
        with pytest.raises(EasyCareInvalidResponseError, match="id_token"):
            OAuthTokens.from_api(data, now=FAKE_NOW)

    def test_from_api_missing_refresh_token_raises(self):
        data = {"id_token": "id"}
        with pytest.raises(EasyCareInvalidResponseError, match="refresh_token"):
            OAuthTokens.from_api(data, now=FAKE_NOW)

    def test_from_api_default_expires_in_when_missing(self):
        data = {"id_token": "id", "refresh_token": "ref"}
        tokens = OAuthTokens.from_api(data, now=FAKE_NOW)
        # default 3600
        assert tokens.expires_at == FAKE_NOW + 3600

    def test_is_expired_true(self):
        tokens = OAuthTokens(
            access_token="a", id_token="b", refresh_token="c", expires_at=FAKE_NOW
        )
        assert tokens.is_expired(now=FAKE_NOW + 1)

    def test_is_expired_false(self):
        tokens = OAuthTokens(
            access_token="a", id_token="b", refresh_token="c", expires_at=FAKE_NOW + 60
        )
        assert not tokens.is_expired(now=FAKE_NOW)

    def test_is_expired_with_margin(self):
        tokens = OAuthTokens(
            access_token="a", id_token="b", refresh_token="c", expires_at=FAKE_NOW + 100
        )
        # pas expiré sans marge
        assert not tokens.is_expired(now=FAKE_NOW)
        # expiré avec marge de 200 s
        assert tokens.is_expired(now=FAKE_NOW, margin_seconds=200)


# ---------------------------------------------------------------------------
# BearerToken
# ---------------------------------------------------------------------------

class TestBearerToken:
    def test_from_api_bearer_field(self):
        tok = BearerToken.from_api({"bearer": "my-bearer", "expires_in": 7200}, now=FAKE_NOW)
        assert tok.bearer == "my-bearer"
        assert tok.expires_at == FAKE_NOW + 7200

    def test_from_api_access_token_fallback(self):
        tok = BearerToken.from_api({"access_token": "at-bearer"}, now=FAKE_NOW)
        assert tok.bearer == "at-bearer"

    def test_from_api_missing_both_raises(self):
        with pytest.raises(EasyCareInvalidResponseError):
            BearerToken.from_api({}, now=FAKE_NOW)

    def test_is_expired(self):
        tok = BearerToken(bearer="x", expires_at=FAKE_NOW + 10)
        assert not tok.is_expired(now=FAKE_NOW)
        assert tok.is_expired(now=FAKE_NOW + 20)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_from_api_all_measures_present(self):
        data = {
            "status": {
                "lastPhMeasure": {"value": 7.4, "date": 1700000000},
                "lastRedoxMeasure": {"value": 650.0, "date": 1700000000},
                "lastTemperatureMeasure": {"value": 25.0, "date": 1700000000},
                "lastPressureMeasure": {"value": 1.2, "date": 1700000000},
            }
        }
        m = Metrics.from_api(data)
        assert m.ph_value == pytest.approx(7.4)
        assert m.chlorine_value == pytest.approx(650.0)
        assert m.temperature_value == pytest.approx(25.0)
        assert m.pressure_value == pytest.approx(1.2)

    def test_from_api_date_unix_timestamp(self):
        data = {"status": {"lastPhMeasure": {"value": 7.0, "date": 1700000000}}}
        m = Metrics.from_api(data)
        assert m.ph_date is not None
        assert m.ph_date.tzinfo == timezone.utc

    def test_from_api_date_iso8601(self):
        data = {"status": {"lastPhMeasure": {"value": 7.0, "date": "2023-11-14T20:53:20Z"}}}
        m = Metrics.from_api(data)
        assert m.ph_date is not None

    def test_from_api_empty_status(self):
        m = Metrics.from_api({"status": {}})
        assert m.ph_value is None
        assert m.chlorine_value is None
        assert m.temperature_value is None
        assert m.pressure_value is None

    def test_from_api_null_values(self):
        data = {"status": {"lastPhMeasure": {"value": None, "date": None}}}
        m = Metrics.from_api(data)
        assert m.ph_value is None
        assert m.ph_date is None

    def test_from_api_missing_status_key(self):
        m = Metrics.from_api({})
        assert m.ph_value is None
        assert m.temperature_value is None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class TestAlerts:
    def test_from_api_with_notifications(self):
        data = {
            "notifications": {
                "1": {"action": "batteryLow", "date": "2024-01-15T10:00:00Z"},
            }
        }
        a = Alerts.from_api(data)
        assert len(a.notifications) == 1
        assert a.notifications[0].action == "batteryLow"

    def test_from_api_empty_dict(self):
        a = Alerts.from_api({"notifications": {}})
        assert a.notifications == ()
        assert a.latest is None

    def test_from_api_sorted_by_date_desc(self):
        data = {
            "notifications": {
                "1": {"action": "batteryLow", "date": "2024-01-10T00:00:00Z"},
                "2": {"action": "connectivityLost", "date": "2024-01-15T00:00:00Z"},
            }
        }
        a = Alerts.from_api(data)
        assert a.notifications[0].action == "connectivityLost"

    def test_latest_action_none_when_empty(self):
        a = Alerts()
        assert a.latest_action == "None"


# ---------------------------------------------------------------------------
# Treatment
# ---------------------------------------------------------------------------

class TestTreatment:
    def test_from_api_with_protocol(self):
        data = {"waterChemistryCorrectionProtocol": {"correctionProtocolType": "chlore"}}
        t = Treatment.from_api(data)
        assert t.value == "chlore"

    def test_from_api_none_protocol(self):
        data = {"waterChemistryCorrectionProtocol": {"correctionProtocolType": "None"}}
        t = Treatment.from_api(data)
        assert t.value == "None"

    def test_from_api_missing_key(self):
        t = Treatment.from_api({})
        assert t.value == "None"
        assert t.date is None


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

class TestPool:
    def test_from_api_with_underscore_id(self):
        data = {"_id": "pool-001", "model": "X"}
        p = Pool.from_api(data)
        assert p.id == "pool-001"

    def test_from_api_with_id_field(self):
        data = {"id": "pool-002", "model": "Y"}
        p = Pool.from_api(data)
        assert p.id == "pool-002"

    def test_from_api_float_conversion_error_defaults(self):
        data = {"model": "X", "volume": "invalid", "latitude": None}
        p = Pool.from_api(data)
        assert p.volume == 0.0
        assert p.latitude == 0.0


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class TestModule:
    def test_from_api_required_field_missing_raises(self):
        with pytest.raises(EasyCareInvalidResponseError):
            Module.from_api({"name": "BPC-X", "id": "1"})  # type manquant

    def test_from_api_with_outputs(self):
        data = {
            "type": "lr-pc",
            "name": "BPC-AABBCC",
            "id": "id-1",
            "serialNumber": "AABBCC",
            "outputs": [{"index": 0, "name": "pompe", "id": "out-0", "totalActivationTime": 600}],
        }
        m = Module.from_api(data)
        assert len(m.outputs) == 1
        assert m.outputs[0].index == 0
        assert m.outputs[0].total_activation_time == 600

    def test_short_name(self):
        m = Module(type="lr-pc", name="BPC-DDEEFF", id="x", serial_number="DDEEFF")
        assert m.short_name == "DDEEFF"

    def test_short_name_no_dash(self):
        m = Module(type="lr-pc", name="NOPREFIX", id="x", serial_number="NOPREFIX")
        assert m.short_name == "NOPREFIX"

    def test_get_output_found(self):
        out = ModuleOutput(index=1, name="spot", id="out-1")
        m = Module(type="lr-pc", name="BPC-X", id="x", serial_number="X", outputs=(out,))
        assert m.get_output(1) is out

    def test_get_output_not_found(self):
        m = Module(type="lr-pc", name="BPC-X", id="x", serial_number="X")
        assert m.get_output(0) is None


# ---------------------------------------------------------------------------
# BPCInput
# ---------------------------------------------------------------------------

class TestBPCInput:
    def test_from_api_pump_active(self):
        data = {"index": 0, "value": 1, "time": "01:30", "origin": 0, "info": [], "tempRef": 6}
        inp = BPCInput.from_api(data)
        assert inp.index == 0
        assert inp.is_on
        assert not inp.is_boosting
        assert inp.temp_ref == 6

    def test_from_api_pump_boosting(self):
        data = {"index": 0, "value": 1, "time": "02:00", "origin": 3, "info": ["boost"]}
        inp = BPCInput.from_api(data)
        assert inp.is_on
        assert inp.is_boosting

    def test_from_api_index_missing_raises(self):
        with pytest.raises(EasyCareInvalidResponseError):
            BPCInput.from_api({"value": 1})

    def test_is_on_false(self):
        inp = BPCInput(index=0, value=0)
        assert not inp.is_on

    def test_is_boosting_false_without_boost_tag(self):
        inp = BPCInput(index=0, value=1, info=("man",))
        assert not inp.is_boosting


# ---------------------------------------------------------------------------
# PoolStatus
# ---------------------------------------------------------------------------

class TestPoolStatus:
    def test_from_api_flat(self):
        data = {"mode": "auto", "powerState": "on", "boostTimeLeft": "00:00"}
        s = PoolStatus.from_api(data)
        assert s.mode == "auto"
        assert s.power_state == "on"
        assert not s.is_boosting

    def test_from_api_nested_pool(self):
        data = {"pool": {"mode": "manual", "powerState": "off"}}
        s = PoolStatus.from_api(data)
        assert s.mode == "manual"

    def test_from_api_nested_status(self):
        data = {"status": {"mode": "continuous", "powerState": "on"}}
        s = PoolStatus.from_api(data)
        assert s.mode == "continuous"

    def test_is_boosting_with_remaining_time(self):
        data = {"boostTimeLeft": "01:30"}
        s = PoolStatus.from_api(data)
        assert s.is_boosting

    def test_is_boosting_false_with_zero(self):
        data = {"boostTimeLeft": "00:00"}
        s = PoolStatus.from_api(data)
        assert not s.is_boosting


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_unix_int(self):
        dt = _parse_timestamp(1700000000)
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_iso8601_with_z(self):
        dt = _parse_timestamp("2023-11-14T20:53:20Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_iso8601_naive_assumes_utc(self):
        dt = _parse_timestamp("2023-11-14T20:53:20")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_date_only(self):
        dt = _parse_timestamp("2023-11-14")
        assert dt is not None

    def test_none_returns_none(self):
        assert _parse_timestamp(None) is None

    def test_invalid_string_returns_none(self):
        assert _parse_timestamp("not-a-date") is None


# ---------------------------------------------------------------------------
# FilterSchedule
# ---------------------------------------------------------------------------

THS = (10, 12, 14, 16, 20, 24, 27, 28, 29, 30, 31, 127)
# Sched AUTO standard pour 27°C : bits 9-18 (10h consécutives : 9h → 19h)
# 0x7FE00 = bits 9..18 = 523264 + ... = 522752? Recalculons :
# bits 9..18 inclus = sum(2**i for i in range(9,19)) = 512+1024+2048+4096+8192+16384+32768+65536+131072+262144 = 523776
MASK_27 = sum(1 << i for i in range(9, 19))  # 523776

SCHED_ROW = (32, 32, 3072, 7168, 61440, 261120, MASK_27, 1046528, 2093056, 4186112, 4186112, 0)

FILTER_SCHED = FilterSchedule(
    thresholds=THS,
    sched=(SCHED_ROW,) * 7,
    rules=(
        CyclicRule(threshold_index=6, threshold_temp=27, duration_min=600, period_min=1440),
    ),
)


class TestFilterSchedule:
    def test_from_program_characteristics_parses_ths(self):
        charac = {"ths": [10, 12, 14], "cyclic": []}
        fs = FilterSchedule.from_program_characteristics(charac)
        assert fs.thresholds == (10, 12, 14)

    def test_from_program_characteristics_parses_sched(self):
        charac = {"ths": [10, 20, 127]}
        sched = [[100, 200, 0]] * 7
        fs = FilterSchedule.from_program_characteristics(charac, sched=sched)
        assert fs.sched is not None
        assert fs.sched[0] == (100, 200, 0)

    def test_from_program_characteristics_parses_cyclic_rules(self):
        charac = {
            "ths": [10, 27, 127],
            "cyclic": [{"th": 1, "dur": 600, "per": 1440}],
        }
        fs = FilterSchedule.from_program_characteristics(charac)
        assert len(fs.rules) == 1
        assert fs.rules[0].threshold_temp == 27
        assert fs.rules[0].duration_min == 600

    def test_from_program_characteristics_empty(self):
        fs = FilterSchedule.from_program_characteristics({})
        assert fs.thresholds == ()
        assert fs.sched is None

    def test_active_threshold_index_ceiling(self):
        # temp=25 → seuil plafond = 27 → index 6
        idx = FILTER_SCHED.active_threshold_index_for_temp(25.0)
        assert idx == 6

    def test_active_threshold_index_exact_match(self):
        # temp=27 → seuil = 27 → index 6
        idx = FILTER_SCHED.active_threshold_index_for_temp(27.0)
        assert idx == 6

    def test_active_threshold_index_above_all(self):
        # temp=35 → tous les seuils réels < 35 → seuil le plus élevé = 31 → index 10
        idx = FILTER_SCHED.active_threshold_index_for_temp(35.0)
        assert idx == 10

    def test_active_threshold_index_skips_sentinel_127(self):
        # La sentinelle 127 ne doit jamais être retournée
        idx = FILTER_SCHED.active_threshold_index_for_temp(200.0)
        assert idx is not None
        assert FILTER_SCHED.thresholds[idx] != 127

    def test_daily_hours_from_sched(self):
        fs = FilterSchedule(
            thresholds=(27,),
            sched=((0b111111,),) * 7,  # 6 bits → 6h
        )
        assert fs.daily_hours_from_sched(27.0, threshold_idx=0) == 6.0

    def test_daily_hours_from_sched_no_sched_returns_none(self):
        fs = FilterSchedule(thresholds=(27,))
        assert fs.daily_hours_from_sched(27.0) is None

    def test_filter_windows_single_contiguous_block(self):
        # bits 9..18 → un seul créneau [9, 19)
        windows = FILTER_SCHED.filter_windows_from_sched(27.0, threshold_idx=6)
        assert windows == [(9, 19)]

    def test_filter_windows_two_separate_blocks(self):
        # bit 5 et bit 22 → deux créneaux séparés
        mask = (1 << 5) | (1 << 22)
        fs = FilterSchedule(thresholds=(20,), sched=((mask,),) * 7)
        windows = fs.filter_windows_from_sched(20.0, threshold_idx=0)
        assert len(windows) == 2
        assert windows[0] == (5, 6)
        assert windows[1] == (22, 23)

    def test_filter_windows_empty_mask(self):
        fs = FilterSchedule(thresholds=(20,), sched=((0,),) * 7)
        windows = fs.filter_windows_from_sched(20.0, threshold_idx=0)
        assert windows == []

    def test_next_filtration_currently_inside_window(self):
        # Créneau [9, 19) — on est à 12h → dans la plage
        with freeze_time("2023-11-14 12:00:00"):
            now = datetime.now(tz=timezone.utc)
            next_start, next_stop = FILTER_SCHED.next_filtration_events(27.0, now, threshold_idx=6)
        # arrêt = 19h aujourd'hui, démarrage = 9h demain
        assert next_stop is not None
        assert next_stop.hour == 19
        assert next_start is not None
        assert next_start.day == now.day + 1 or next_start.day == 1  # lendemain

    def test_next_filtration_before_first_window(self):
        # on est à 7h → avant la plage [9, 19)
        with freeze_time("2023-11-14 07:00:00"):
            now = datetime.now(tz=timezone.utc)
            next_start, next_stop = FILTER_SCHED.next_filtration_events(27.0, now, threshold_idx=6)
        assert next_start is not None
        assert next_start.hour == 9
        assert next_stop is not None
        assert next_stop.hour == 19

    def test_next_filtration_after_last_window_rollover(self):
        # on est à 21h → toutes les plages passées → rollover J+1
        with freeze_time("2023-11-14 21:00:00"):
            now = datetime.now(tz=timezone.utc)
            next_start, next_stop = FILTER_SCHED.next_filtration_events(27.0, now, threshold_idx=6)
        assert next_start is not None
        assert next_start.hour == 9
        # lendemain
        assert next_start.day != now.day or next_start.month != now.month

    def test_next_filtration_no_sched_returns_none(self):
        fs = FilterSchedule(thresholds=(27,))
        now = datetime.now(tz=timezone.utc)
        start, stop = fs.next_filtration_events(27.0, now)
        assert start is None
        assert stop is None

    def test_cyclic_rule_daily_hours(self):
        rule = CyclicRule(threshold_index=0, threshold_temp=27, duration_min=600, period_min=1440)
        # 600/1440 * 24 = 10h
        assert rule.daily_hours == pytest.approx(10.0)
