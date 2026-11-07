import json
from dataclasses import dataclass

NO_DATA = "данных нет"


class InputError(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InputError(f"Invalid JSON constant: {value}.")


def _clean(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"{field} must be a string or null.")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise InputError(f"{field} contains an invalid Unicode character.")
    return value.strip() or None


def _spec_name(value: object) -> str:
    name = _clean(value, "Specification name")
    if name is None:
        raise InputError("Specification names cannot be blank.")
    return name


@dataclass(frozen=True)
class Product:
    name: str | None
    manufacturer: str | None
    specs: dict[str, str | None]
    description: str | None

    @classmethod
    def from_json(cls, raw: str) -> "Product":
        """Validate a single product and add empty rows for the supplied checklist."""
        try:
            data = json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
        except json.JSONDecodeError as exc:
            raise InputError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}.") from exc
        except InputError:
            raise
        except (ValueError, RecursionError) as exc:
            raise InputError("Input JSON exceeds parser limits.") from exc

        if not isinstance(data, dict):
            raise InputError("Input JSON must be an object.")
        raw_specs = data.get("specs")
        if raw_specs is not None and not isinstance(raw_specs, dict):
            raise InputError("specs must be an object or null.")
        specs = {}
        for key, value in (raw_specs or {}).items():
            name = _spec_name(key)
            if name in specs:
                raise InputError(f"Duplicate specification name: {name!r}.")
            specs[name] = _clean(value, f"specs[{name!r}]")

        expected = data.get("expected_specs")
        if expected is not None and not isinstance(expected, list):
            raise InputError("expected_specs must be an array of names or null.")
        for key in expected or []:
            specs.setdefault(_spec_name(key), None)

        return cls(
            _clean(data.get("name"), "name"),
            _clean(data.get("manufacturer"), "manufacturer"),
            specs,
            _clean(data.get("description"), "description"),
        )

    def missing_fields(self) -> list[str]:
        """Return field paths an editor can use to complete the source record."""
        missing = [
            field for field in ("name", "manufacturer", "description") if not getattr(self, field)
        ]
        if not any(self.specs.values()):
            missing.append("specs")
        missing.extend(f"specs.{name}" for name, value in self.specs.items() if value is None)
        return missing
