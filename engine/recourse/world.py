"""A synthetic city: households on food-security cards, and three government registries.

Everything here is made up and seeded. Each registry record keeps `true_pid`, the
person it really belongs to (None for the many people who never applied), so the
demo can count how often a matching rule cuts off the wrong family. The rules
never see `true_pid`.
"""

import random
from dataclasses import dataclass, field

POOR = [
    "Falaknuma", "Chandrayangutta", "Yakutpura", "Bahadurpura", "Malakpet",
    "Borabanda", "Amberpet", "Musheerabad", "Uppal", "LB Nagar", "Tolichowki", "Kukatpally",
]
RICH = ["Banjara Hills", "Jubilee Hills", "Gachibowli", "Madhapur", "Begumpet", "Kondapur"]

MUSLIM_PREFIX = ["Mohammed", "Md", "Syed", "Shaik", "Mohd", ""]
MUSLIM_MALE = [
    "Ali", "Ahmed", "Imran", "Khaja", "Rahman", "Yousuf", "Ismail", "Ibrahim", "Hussain",
    "Mahmood", "Akbar", "Salim", "Rafiq", "Azeem", "Moin", "Javeed", "Arif", "Asif", "Habeeb",
    "Iqbal", "Jameel", "Kareem", "Majeed", "Mujeeb", "Naseer", "Owais", "Qadeer", "Riyaz",
    "Sameer", "Shafi", "Tahir", "Wajid", "Zaheer", "Abrar", "Ghouse", "Mustafa", "Nawaz",
    "Raheem", "Sadiq", "Younus",
]
MUSLIM_SURNAME = ["Khan", "Qureshi", "Siddiqui", "Ansari", "Hashmi", "Quadri", "Farooqui", "Baig",
                  "Pasha", "Hyder", "", "", ""]
MUSLIM_FEMALE = [
    "Fatima", "Ayesha", "Amina", "Zareena", "Shabana", "Nasreen", "Rukhsana", "Sultana",
    "Parveen", "Haseena", "Bismillah", "Afreen", "Farzana", "Gulshan", "Hajra", "Jabeen",
    "Kauser", "Mehrunnisa", "Naseema", "Rehana", "Salma", "Tabassum", "Yasmeen", "Zubeda",
]
MUSLIM_FEMALE_SUFFIX = ["Begum", "Bee", "Khatoon", ""]

HINDU_MALE = [
    "Venkatesh", "Srinivas", "Ramesh", "Suresh", "Anjaiah", "Yadaiah", "Mallesh", "Narsimha",
    "Raju", "Krishna", "Ravi", "Mahesh", "Shankar", "Balraj", "Prakash", "Satyanarayana",
    "Anil", "Bhaskar", "Chandraiah", "Damodar", "Ganesh", "Hanumanthu", "Jagadish", "Kistaiah",
    "Lingaiah", "Madhu", "Nagaraju", "Pentaiah", "Rajender", "Sailu", "Thirupathi", "Upender",
    "Venkanna", "Yellaiah", "Bikshapathi", "Komuraiah", "Sathaiah", "Ramulu", "Srisailam", "Veeresham",
]
HINDU_FEMALE = [
    "Lakshmi", "Sujatha", "Padma", "Saritha", "Swapna", "Anitha", "Manjula", "Yadamma",
    "Pochamma", "Renuka", "Sunitha", "Kavitha", "Bhagya", "Durga", "Jyothi", "Kalpana",
    "Laxmamma", "Mamatha", "Narsamma", "Radha", "Sarojana", "Shobha", "Uma", "Vijaya",
]
HINDU_SURNAME = ["Reddy", "Goud", "Yadav", "Rao", "Naidu", "Chary", "Mudiraj", "Netha", "Kumar",
                 "Bandari", "Gaddam", "Kommu", "Madiga", "Pittala", "Sangem", "Thota", "Vadde",
                 "Erukala", "Bolla", "Chilukuri"]

CHRISTIAN_MALE = ["Joseph", "John", "Daniel", "David", "Samuel", "Paul", "Stephen", "Moses",
                  "Isaac", "Peter", "Thomas", "Prabhudas"]
CHRISTIAN_FEMALE = ["Mary", "Grace", "Esther", "Ruth", "Sarah", "Rachel", "Suneetha", "Hepsiba", "Lydia"]
CHRISTIAN_SURNAME = ["Raj", "Kumar", "Prasad", "Babu", "Solomon", "Jacob", "Emmanuel"]

WORK = [
    "rickshaw puller", "auto driver", "daily-wage labourer", "domestic worker", "street vendor",
    "tailor", "construction worker", "security guard", "beedi roller", "mechanic's helper",
]
DEPARTMENTS = ["Revenue", "Police", "Health", "School Education", "Municipal Administration", "Irrigation"]
RTO = ["TS09", "TS10", "TS11", "TS12", "TS13", "TS07"]


@dataclass
class Person:
    pid: int
    name: str
    relative: str  # the "son of / wife of / daughter of" name, as on the ID card
    relation: str  # "S/o", "W/o", "D/o"
    sex: str
    community: str
    birth_year: int
    status: str = "living"  # or "deceased" (still listed on the card)
    died: int | None = None


@dataclass
class Household:
    hid: int
    card: str
    application: str
    locality: str
    work: str
    members: list[Person] = field(default_factory=list)


@dataclass
class Record:
    registry: str  # "vehicles", "income_tax", "payroll"
    rid: str
    name: str
    relative: str
    relation: str
    locality: str
    year: int  # registration year, assessment year, or joining year
    detail: str
    true_pid: int | None


def _male(rng, community):
    if community == "muslim":
        parts = [rng.choice(MUSLIM_PREFIX), rng.choice(MUSLIM_MALE), rng.choice(MUSLIM_SURNAME)]
    elif community == "hindu":
        parts = [rng.choice(HINDU_MALE), rng.choice(HINDU_SURNAME)]
    else:
        parts = [rng.choice(CHRISTIAN_MALE), rng.choice(CHRISTIAN_SURNAME)]
    return " ".join(p for p in parts if p)


def _female(rng, community, husband=None):
    if community == "muslim":
        parts = [rng.choice(MUSLIM_FEMALE), rng.choice(MUSLIM_FEMALE_SUFFIX)]
    elif community == "hindu":
        sur = husband.split()[-1] if husband else rng.choice(HINDU_SURNAME)
        parts = [rng.choice(HINDU_FEMALE), sur]
    else:
        sur = husband.split()[-1] if husband else rng.choice(CHRISTIAN_SURNAME)
        parts = [rng.choice(CHRISTIAN_FEMALE), sur]
    return " ".join(p for p in parts if p)


def _community(rng):
    r = rng.random()
    return "muslim" if r < 0.42 else "hindu" if r < 0.92 else "christian"


def _plate(rng):
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return f"{rng.choice(RTO)}{rng.choice(letters)}{rng.choice(letters)}{rng.randint(1000, 9999)}"


def _variant(rng, name):
    """How the same person's name can look in another department's database."""
    toks = name.split()
    r = rng.random()
    if toks[0] in ("Mohammed", "Mohd") and r < 0.5:
        toks[0] = "Md"
    elif toks[0] == "Md" and r < 0.5:
        toks[0] = "Mohammed"
    elif len(toks) > 2 and r < 0.3:
        toks = toks[:-1]  # surname dropped
    return " ".join(toks)


class World:
    def __init__(self, seed: int = 7, households: int = 1000):
        self.rng = random.Random(seed)
        self.households: list[Household] = []
        self.records: list[Record] = []
        self._pid = 0
        self._ids: set[str] = set()
        for h in range(households):
            self.households.append(self._household(h))
        self._true_records()
        self._background(vehicles=3000, income_tax=2400, payroll=800)
        self.spotlight: dict[str, int] = {}
        self._spotlight()

    def person(self, pid: int) -> Person:
        return self._people[pid]

    def _new_pid(self):
        self._pid += 1
        return self._pid

    def _household(self, h):
        rng = self.rng
        com = _community(rng)
        loc = rng.choice(POOR)
        head_father = _male(rng, com)
        head = Person(self._new_pid(), _male(rng, com), head_father, "S/o", "M", com, rng.randint(1955, 1992))
        wife = Person(self._new_pid(), _female(rng, com, head.name), head.name, "W/o", "F", com,
                      head.birth_year + rng.randint(1, 8))
        members = [head, wife]
        if rng.random() < 0.08:  # the husband died; the card was never updated
            head.status = "deceased"
            head.died = rng.randint(2016, 2024)
        for _ in range(rng.randint(0, 3)):
            if rng.random() < 0.5:
                child = Person(self._new_pid(), _male(rng, com), head.name, "S/o", "M", com,
                               wife.birth_year + rng.randint(18, 30))
            else:
                child = Person(self._new_pid(), _female(rng, com), head.name, "D/o", "F", com,
                               wife.birth_year + rng.randint(18, 30))
            members.append(child)
        hh = Household(h + 1, f"FSC-HYD-{rng.randint(100000, 999999)}", f"RV-2026-{h + 1:06d}", loc,
                       rng.choice(WORK), members)
        return hh

    @property
    def _people(self):
        if not hasattr(self, "_people_cache"):
            self._people_cache = {p.pid: p for hh in self.households for p in hh.members}
        return self._people_cache

    def _uid(self, make):
        while True:
            x = make()
            if x not in self._ids:
                self._ids.add(x)
                return x

    def _record(self, registry, name, relative, relation, locality, true_pid):
        rng = self.rng
        if registry == "vehicles":
            rid = self._uid(lambda: _plate(rng))
            year = rng.randint(2012, 2026)
            detail = rng.choice(["Maruti Swift", "Hyundai i20", "Honda City", "Toyota Innova", "Tata Nexon",
                                 "Mahindra XUV300", "Maruti Ertiga", "Kia Seltos"])
        elif registry == "income_tax":
            rid = self._uid(lambda: f"ITR-AY{rng.choice(['2023-24', '2024-25', '2025-26'])}-{rng.randint(100000, 999999)}")
            year = int(rid[6:10]) + 1
            detail = f"assessed income Rs {rng.randint(5, 40) * 50000:,}"
        else:
            rid = self._uid(lambda: f"EMP-TSG-{rng.randint(100000, 999999)}")
            year = rng.randint(1998, 2025)
            detail = f"{rng.choice(DEPARTMENTS)} Department"
        return Record(registry, rid, name, relative, relation, locality, year, detail, true_pid)

    def _true_records(self):
        """About one household in ten really is outside the scheme."""
        rng = self.rng
        for hh in self.households:
            if rng.random() >= 0.10:
                continue
            living_adults = [p for p in hh.members if p.status == "living" and p.birth_year < 2004]
            p = rng.choice(living_adults)
            registry = rng.choices(["vehicles", "income_tax", "payroll"], [0.5, 0.3, 0.2])[0]
            moved = rng.random() < 0.3  # registered at another address
            loc = rng.choice(POOR + RICH) if moved else hh.locality
            name = _variant(rng, p.name) if rng.random() < 0.4 else p.name
            self.records.append(self._record(registry, name, p.relative, p.relation, loc, p.pid))

    def _scripted(self, key, locality, work, members, records):
        hid = len(self.households) + 1
        people = []
        for name, rel, relation, sex, born, died in members:
            p = Person(self._new_pid(), name, rel, relation, sex, "", born)
            if died:
                p.status, p.died = "deceased", died
            people.append(p)
        self.households.append(Household(hid, f"FSC-HYD-{700000 + hid}", f"RV-2026-{hid:06d}", locality, work, people))
        for registry, rid, name, rel, relation, loc, year, detail, owner in records:
            self._ids.add(rid)
            self.records.append(Record(registry, rid, name, rel, relation, loc, year, detail,
                                       people[owner].pid if owner is not None else None))
        self.spotlight[key] = hid
        if hasattr(self, "_people_cache"):
            del self._people_cache

    def _spotlight(self):
        """The households the demo walks through. Their records are written by hand."""
        # Modelled on Bismillah Bee's case (Al Jazeera, Jan 2024): her late husband, a rickshaw
        # puller, was matched to someone else's car. The names and records here are invented.
        self._scripted("amina", "Falaknuma", "domestic worker", [
            ("Syed Ali", "Syed Mahmood", "S/o", "M", 1961, 2019),
            ("Amina Begum", "Syed Ali", "W/o", "F", 1966, None),
            ("Syed Imran", "Syed Ali", "S/o", "M", 1990, None),
        ], [
            ("vehicles", "TS09EX4521", "Syed Ali Khan", "Syed Mahmood", "S/o", "Banjara Hills", 2022,
             "Toyota Innova", None),
        ])
        # Really does own a car, registered at his brother's address in Gachibowli.
        self._scripted("prakash", "Kukatpally", "auto driver", [
            ("Prakash Reddy", "Narsimha Reddy", "S/o", "M", 1979, None),
            ("Swapna Reddy", "Prakash Reddy", "W/o", "F", 1984, None),
        ], [
            ("vehicles", "TS07FK2290", "Prakash Reddy", "Narsimha Reddy", "S/o", "Gachibowli", 2023,
             "Maruti Ertiga", 0),
        ])
        # Nothing on any registry: eligible under every ruleset.
        self._scripted("lakshmi", "Uppal", "street vendor", [
            ("Lakshmi Mudiraj", "Balraj Mudiraj", "W/o", "F", 1975, None),
            ("Balraj Mudiraj", "Yadaiah Mudiraj", "S/o", "M", 1970, None),
            ("Renuka Mudiraj", "Balraj Mudiraj", "D/o", "F", 1999, None),
        ], [])
        # The son really is a police constable.
        self._scripted("joseph", "Secunderabad", "security guard", [
            ("Joseph Prasad", "David Prasad", "S/o", "M", 1964, None),
            ("Mary Prasad", "Joseph Prasad", "W/o", "F", 1968, None),
            ("Daniel Prasad", "Joseph Prasad", "S/o", "M", 1994, None),
        ], [
            ("payroll", "EMP-TSG-418820", "Daniel Prasad", "Joseph Prasad", "S/o", "Secunderabad", 2019,
             "Police Department", 2),
        ])
        # A common name: two strangers' records, each enough to deny on its own.
        self._scripted("imran", "Yakutpura", "tailor", [
            ("Mohammed Imran", "Mohammed Yousuf", "S/o", "M", 1983, None),
            ("Nasreen Begum", "Mohammed Imran", "W/o", "F", 1987, None),
        ], [
            ("vehicles", "TS10AB7731", "Md Imran", "Md Yousuf Khan", "S/o", "Tolichowki", 2021,
             "Hyundai i20", None),
            ("income_tax", "ITR-AY2025-26-604418", "Mohd Imran Siddiqui", "Mohammed Yusuf", "S/o",
             "Malakpet", 2026, "assessed income Rs 9,50,000", None),
        ])

    def _background(self, vehicles, income_tax, payroll):
        """Everyone else in the city who owns a car, pays tax or draws a government salary."""
        rng = self.rng
        for registry, n in (("vehicles", vehicles), ("income_tax", income_tax), ("payroll", payroll)):
            for _ in range(n):
                com = _community(rng)
                loc = rng.choice(RICH) if rng.random() < 0.55 else rng.choice(POOR)
                if rng.random() < 0.8:
                    name, rel, relation = _male(rng, com), _male(rng, com), "S/o"
                else:
                    husband = _male(rng, com)
                    name, rel, relation = _female(rng, com, husband), husband, "W/o"
                self.records.append(self._record(registry, name, rel, relation, loc, None))
