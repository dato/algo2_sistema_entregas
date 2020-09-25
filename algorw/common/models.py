from dataclasses import dataclass, field


@dataclass
class Repo:
    name: str = field(init=False)
    owner: str = field(init=False)
    full_name: str

    def __post_init__(self):
        self.owner, self.name = self.full_name.split("/", 1)
