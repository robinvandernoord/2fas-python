import typing
from typing import Optional

from configuraptor import TypedConfig, asdict, asjson
from pyotp import TOTP

AnyDict = dict[str, typing.Any]


class OtpDetails(TypedConfig):
    link: str
    tokenType: str
    source: str
    label: Optional[str] = None
    account: Optional[str] = None
    digits: Optional[int] = None
    period: Optional[int] = None


class OrderDetails(TypedConfig):
    position: int


class IconCollectionDetails(TypedConfig):
    id: str


class IconDetails(TypedConfig):
    selected: str
    iconCollection: IconCollectionDetails


class TwoFactorAuthDetails(TypedConfig):
    name: str
    secret: str
    updatedAt: int
    serviceTypeID: Optional[str]
    otp: OtpDetails
    order: OrderDetails
    icon: IconDetails
    groupId: Optional[str] = None  # todo: groups are currently not supported!

    _topt: Optional[TOTP] = None  # lazily loaded when calling .totp or .generate()

    @property
    def totp(self) -> TOTP:
        if not self._topt:
            self._topt = TOTP(self.secret)
        return self._topt

    def generate(self) -> str:
        return self.totp.now()

    def generate_int(self) -> int:
        # !!! usually not prefered, because this drops leading zeroes!!
        return int(self.totp.now())

    def as_dict(self) -> AnyDict:
        return asdict(self, with_top_level_key=False, exclude_internals=2)

    def as_json(self) -> str:
        return asjson(self, with_top_level_key=False, indent=2, exclude_internals=2)

    def __str__(self) -> str:
        return f"<2fas '{self.name}'>"

    def __repr__(self) -> str:
        return self.as_json()


T_TypedConfig = typing.TypeVar("T_TypedConfig", bound=TypedConfig)


def into_class(entries: list[AnyDict], klass: typing.Type[T_TypedConfig]) -> list[T_TypedConfig]:
    return [klass.load(d) for d in entries]
