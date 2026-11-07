from dataclasses import asdict, dataclass

from .product import NO_DATA, Product

FOCUSES = {
    "selection": (
        "Подбор прибора начинается со сверки требований к измерению и параметров модели. "
        "При сравнении нескольких предложений стоит привести значения к одинаковым "
        "единицам и проверить, по каким характеристикам поставщики приводят данные.",
        "Инженерам, которые подбирают прибор по требованиям проекта. Карточка помогает "
        "сравнить параметры моделей и подготовить вопросы поставщику.",
    ),
    "replacement": (
        "При замене прибора полезно выписать маркировку установленной модели и требования "
        "к месту установки. Затем можно сверить их с данными выбранной позиции и "
        "уточнить у поставщика условия, от которых зависит взаимозаменяемость.",
        "Сервисным инженерам, которые ищут замену установленному прибору. Карточка "
        "помогает сопоставить исходные параметры и проверить, какие данные нужны для замены.",
    ),
    "procurement": (
        "При подготовке запроса поставщику полезно сопоставить параметры позиции с "
        "закупочной спецификацией. Если от нужной характеристики зависит выбор "
        "исполнения, её можно вынести отдельной строкой в запрос на коммерческое предложение.",
        "Специалистам по закупкам, которые готовят запрос поставщику. Карточка помогает "
        "описать позицию, сопоставить предложения и собрать вопросы по комплектации.",
    ),
}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Candidates:
    facts: list[str]
    queries: list[str]
    excerpts: list[str]

    @classmethod
    def from_product(cls, product: Product) -> "Candidates":
        """Build the candidate lists the model may reference by zero-based index."""
        name = _one_line(product.name or "измерительный прибор")
        manufacturer = _one_line(product.manufacturer or "")
        facts = []
        queries = [f"{name} характеристики", f"купить {name}", f"{name} для закупки"]
        if manufacturer:
            queries.insert(0, f"{name} {manufacturer}")
        for field, value in product.specs.items():
            if value is None:
                continue
            fact = f"{_one_line(field)} — {_one_line(value)}"
            if len(fact) <= 150:
                facts.append(fact)
                queries.append(f"{name} {_one_line(value)}")

        queries = list(dict.fromkeys(query for query in queries if len(query) <= 150))
        if len(queries) < 3:
            queries.extend(
                query
                for query in (
                    "купить измерительный прибор",
                    "измерительный прибор характеристики",
                    "подбор измерительных приборов",
                )
                if query not in queries
            )
        excerpts = [
            paragraph.strip()
            for paragraph in (product.description or "").splitlines()
            if 0 < len(paragraph.strip()) <= 250
        ]
        return cls(facts[:32], queries[:32], excerpts[:16])


@dataclass(frozen=True)
class Plan:
    focus: str
    fact_ids: list[int]
    query_ids: list[int]
    excerpt_id: int | None

    @classmethod
    def from_data(cls, data: object, candidates: Candidates) -> "Plan":
        """Validate structure, uniqueness and candidate references from the model."""
        if not isinstance(data, dict) or set(data) != {
            "focus",
            "fact_ids",
            "query_ids",
            "excerpt_id",
        }:
            raise PlanError("Unexpected editorial plan fields.")
        focus = data["focus"]
        if not isinstance(focus, str) or focus not in FOCUSES:
            raise PlanError("Unknown editorial focus.")
        fact_ids = _indices(data["fact_ids"], len(candidates.facts), 0, 4)
        query_ids = _indices(data["query_ids"], len(candidates.queries), 3, 5)
        excerpt_id = data["excerpt_id"]
        if excerpt_id is not None:
            _indices([excerpt_id], len(candidates.excerpts), 1, 1)
        return cls(focus, fact_ids, query_ids, excerpt_id)


def _indices(value: object, size: int, minimum: int, maximum: int) -> list[int]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PlanError("Unexpected number of candidate indices.")
    if any(type(index) is not int or not 0 <= index < size for index in value):
        raise PlanError("Candidate index is out of range.")
    if len(set(value)) != len(value):
        raise PlanError("Candidate indices must be unique.")
    return value


def _one_line(value: str) -> str:
    return " ".join(value.split())


@dataclass(frozen=True)
class Card:
    seo_title: str
    seo_description: str
    specifications: dict[str, str]
    search_queries: list[str]
    commercial: str
    missing_fields: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable product card."""
        return asdict(self)

    def to_markdown(self) -> str:
        """Render the draft with source text escaped as Markdown literals."""
        specifications = [
            f"- **{_markdown(key)}** — {_markdown(value)}"
            for key, value in self.specifications.items()
        ] or [f"- {NO_DATA}"]
        missing = [f"- {_markdown(field)} — {NO_DATA}" for field in self.missing_fields] or [
            "- По заполненным полям уточнений нет."
        ]
        description = "\n\n".join(
            _markdown(paragraph) for paragraph in self.seo_description.split("\n\n")
        )
        return "\n".join(
            [
                f"# {_markdown(self.seo_title)}",
                "",
                "## SEO-описание",
                "",
                description,
                "",
                "## Характеристики",
                "",
                *specifications,
                "",
                "## Поисковые запросы",
                "",
                *(f"- {_markdown(query)}" for query in self.search_queries),
                "",
                "## Для менеджера",
                "",
                _markdown(self.commercial),
                "",
                "## Требует уточнения",
                "",
                *missing,
            ]
        )


def _markdown(value: str) -> str:
    return "".join("\\" + char if char in "\\`*_{}[]<>#~|&" else char for char in _one_line(value))


def _title(product: Product) -> str:
    name = _one_line(product.name or "Измерительный прибор")
    manufacturer = _one_line(product.manufacturer or "")
    if len(name) > 70:
        prefix = name[:69]
        if name[69] != " " and " " in prefix:
            prefix = prefix.rsplit(" ", 1)[0]
        return prefix.rstrip() + "…"
    if manufacturer and manufacturer.casefold() not in name.casefold():
        combined = f"{name} — {manufacturer}"
        if len(combined) <= 70:
            return combined
    return name


def render_card(product: Product, candidates: Candidates, plan: Plan) -> Card:
    """Compose a draft using vetted copy and verbatim values from the input."""
    title = _title(product)
    focus, commercial = FOCUSES[plan.focus]
    name = _one_line(product.name or "Измерительный прибор")
    subject = name if len(name) <= 120 else title
    intro = (
        f"«{subject}» — контрольно-измерительный прибор. Карточка помогает сопоставить "
        "параметры позиции с требованиями проекта, заявки на закупку или замены оборудования."
    )
    missing = product.missing_fields()
    availability = (
        "По позициям с пометкой «данных нет» запросите сведения у поставщика. "
        "Уточнения лучше получить до согласования заказа: от них может зависеть "
        "выбор исполнения и возможность применения прибора в ваших условиях."
        if missing
        else "В карточке собраны параметры из исходных данных. При согласовании заказа "
        "сверьте их с паспортом конкретного исполнения, особенно если поставщик "
        "предлагает несколько вариантов с похожими обозначениями."
    )
    guidance = [
        focus,
        availability,
        (
            "Для технического согласования приложите к запросу перечень обязательных "
            "параметров. Если в одном заказе несколько приборов, перечислите требования "
            "к каждой позиции отдельно и согласуйте обозначение модели и комплект поставки."
        ),
    ]
    details = []
    if plan.excerpt_id is not None:
        excerpt = candidates.excerpts[plan.excerpt_id]
        punctuation = "" if excerpt.endswith((".", "…", "!", "?")) else "."
        source = f"В исходном описании указано: «{excerpt}»{punctuation}"
        commercial += f" {source}"
        if len("\n\n".join([intro, source, *guidance])) <= 1200:
            details.append(source)

    selected = []
    for index in plan.fact_ids:
        fact = candidates.facts[index]
        fact_paragraph = "Указанные параметры: " + "; ".join([*selected, fact]) + "."
        if len("\n\n".join([intro, *details, fact_paragraph, *guidance])) <= 1200:
            selected.append(fact)
    if selected:
        details.append("Указанные параметры: " + "; ".join(selected) + ".")

    return Card(
        title,
        "\n\n".join([intro, *details, *guidance]),
        {key: value or NO_DATA for key, value in product.specs.items()},
        [candidates.queries[index] for index in plan.query_ids],
        commercial,
        missing,
    )
