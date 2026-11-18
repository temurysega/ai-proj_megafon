# inputs: brief.md
"""Run with Python 3. The adjacent brief.md supplies all case data."""

import re
from fractions import Fraction
from pathlib import Path


def case_number(pattern, source):
    match = re.search(pattern, source)
    if not match:
        raise ValueError(f"Missing case parameter matching {pattern!r}")
    return int("".join(match.group(1).split()))


def main():
    source = Path(__file__).with_name("brief.md").read_text(encoding="utf-8")
    rows = {}
    for line in source.splitlines():
        if not line.startswith("|"):
            continue
        channel, screen, registered, paid, tickets = (
            cell.strip() for cell in line.strip("|").split("|")
        )
        if not registered.isdigit():
            continue
        key = channel, screen
        if key in rows:
            raise ValueError(f"Duplicate row {key}")
        rows[key] = int(registered), int(paid), int(tickets)

    volume = case_number(r"ожидается ([\d ]+) регистраций", source)
    referral = case_number(r"(\d+)% по рекомендации", source)
    ads = case_number(r"(\d+)% из рекламы", source)
    unit_value = case_number(r"составляет ([\d ]+) ₽", source)
    ticket_cost = case_number(r"обращения стоит ([\d ]+) ₽", source)
    mix = {"По рекомендации": Fraction(referral, 100), "Реклама": Fraction(ads, 100)}
    screens = ("Текущий", "Новый")
    assert sum(mix.values()) == 1
    assert set(rows) == {(channel, screen) for channel in mix for screen in screens}
    comparisons = {}
    for screen in screens:
        totals = [0, 0, 0]
        expected_paid = expected_tickets = Fraction(0)
        for channel, weight in mix.items():
            group = rows[channel, screen]
            registrations, paid, tickets = group
            assert 0 <= paid <= registrations and registrations > 0 and tickets >= 0
            conversion = Fraction(paid, registrations)
            contact_rate = Fraction(tickets, registrations)
            totals = [total + count for total, count in zip(totals, group)]
            expected_paid += volume * weight * conversion
            expected_tickets += volume * weight * contact_rate
            print(f"{channel} / {screen}: paid {float(conversion):.1%}, "
                  f"tickets per 100 registrations {float(100 * contact_rate):.1f}")

        contribution = expected_paid * unit_value - expected_tickets * ticket_cost
        comparisons[screen] = expected_paid, expected_tickets, contribution
        print(f"{screen}: observed {totals[1]}/{totals[0]} = {totals[1]/totals[0]:.1%}; "
              f"mix-adjusted {float(expected_paid / volume):.1%}; "
              f"paid {expected_paid}, tickets {expected_tickets}, "
              f"support cost {expected_tickets * ticket_cost}, contribution {contribution}")

    current, new = (comparisons[screen] for screen in screens)
    change_paid, change_tickets, change_value = (
        next_value - current_value for next_value, current_value in zip(new, current)
    )
    break_even = change_tickets * ticket_cost / (unit_value * volume)
    print(f"New minus current: paid {change_paid}, tickets {change_tickets}, "
          f"contribution {change_value}, per registration {float(change_value / volume):.2f}; "
          f"break-even conversion lift {float(break_even):.2%}.")
    # Proposed pilot allocation, chosen for this memo.
    treatment_share = Fraction(1, 10)
    print(f"At a {float(treatment_share):.0%} pilot share: incremental tickets "
          f"{change_tickets * treatment_share}, total tickets "
          f"{current[1] + change_tickets * treatment_share}, incremental contribution "
          f"{change_value * treatment_share}.")


if __name__ == "__main__":
    main()
