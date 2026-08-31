import json
import os
from pathlib import Path
from dataclasses import dataclass, field

TARIFF_DIR = Path(__file__).parent.parent.parent / "config" / "tariffs"


@dataclass
class Slab:
    slab_number: int
    min_units: int
    max_units: int | None
    rate_per_unit: float
    description: str


@dataclass
class TariffConfig:
    tariff_name: str
    region: str
    version: str
    currency: str
    billing_period_months: int
    slabs: list[Slab] = field(default_factory=list)
    effective_date: str = ""


@dataclass
class SlabBreakdown:
    slab_number: int
    min_units: int
    max_units: int | None
    units_in_slab: float
    rate_per_unit: float
    charge: float
    description: str


@dataclass
class BillingResult:
    total_kwh: float
    total_charge: float
    currency: str
    slab_breakdown: list[SlabBreakdown]
    tariff_version: str
    period_type: str
    period_months: int


def load_tariff(tariff_name: str = "tamil_nadu_domestic") -> TariffConfig:
    tariff_file = TARIFF_DIR / f"{tariff_name}.json"
    if not tariff_file.exists():
        raise FileNotFoundError(f"Tariff config not found: {tariff_file}")

    with open(tariff_file, "r") as f:
        data = json.load(f)

    slabs = [
        Slab(
            slab_number=s["slab_number"],
            min_units=s["min_units"],
            max_units=s.get("max_units"),
            rate_per_unit=s["rate_per_unit"],
            description=s["description"],
        )
        for s in data["slabs"]
    ]

    return TariffConfig(
        tariff_name=data["tariff_name"],
        region=data["region"],
        version=data["version"],
        currency=data.get("currency", "INR"),
        billing_period_months=data.get("billing_period_months", 2),
        slabs=slabs,
        effective_date=data.get("effective_date", ""),
    )


def calculate_billing(total_kwh: float, tariff: TariffConfig | None = None, period_type: str = "billing_period") -> BillingResult:
    if tariff is None:
        tariff = load_tariff()

    if total_kwh < 0:
        raise ValueError("total_kwh must be non-negative")

    breakdown: list[SlabBreakdown] = []
    remaining = total_kwh

    for slab in tariff.slabs:
        if remaining <= 0:
            break

        if slab.max_units is not None:
            slab_capacity = slab.max_units - slab.min_units + 1
        else:
            slab_capacity = float("inf")

        units_in_slab = min(remaining, slab_capacity)
        charge = units_in_slab * slab.rate_per_unit

        breakdown.append(
            SlabBreakdown(
                slab_number=slab.slab_number,
                min_units=slab.min_units,
                max_units=slab.max_units,
                units_in_slab=round(units_in_slab, 4),
                rate_per_unit=slab.rate_per_unit,
                charge=round(charge, 2),
                description=slab.description,
            )
        )

        remaining -= units_in_slab

    total_charge = sum(s.charge for s in breakdown)

    return BillingResult(
        total_kwh=round(total_kwh, 4),
        total_charge=round(total_charge, 2),
        currency=tariff.currency,
        slab_breakdown=breakdown,
        tariff_version=tariff.version,
        period_type=period_type,
        period_months=tariff.billing_period_months if period_type == "billing_period" else 1,
    )
