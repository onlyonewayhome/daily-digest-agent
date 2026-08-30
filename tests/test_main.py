from daily_digest_agent.main import parser


def test_delivery_cli_commands_parse():
    show = parser().parse_args(["show-deliveries", "--limit", "5", "--config", "config/example.yaml"])
    assert show.command == "show-deliveries"
    assert show.limit == 5

    detail = parser().parse_args(["show-delivery", "--id", "delivery-id"])
    assert detail.command == "show-delivery"
    assert detail.id == "delivery-id"

    retry = parser().parse_args(["retry-delivery", "--id", "delivery-id"])
    assert retry.command == "retry-delivery"
    assert retry.id == "delivery-id"


def test_operator_cli_commands_parse():
    reservations = parser().parse_args([
        "show-budget-reservations", "--month", "2026-08", "--state", "reserved", "--limit", "10",
    ])
    assert reservations.month == "2026-08"
    assert reservations.state == "reserved"
    assert reservations.limit == 10

    release = parser().parse_args([
        "release-budget-reservation", "--id", "reservation-id", "--reason", "no provider charge",
        "--unsafe-release",
    ])
    assert release.unsafe_release

    stale = parser().parse_args(["show-stale", "--older-than-hours", "12"])
    assert stale.older_than_hours == 12