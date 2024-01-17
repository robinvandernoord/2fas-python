import typing
from typing import Optional

from configuraptor import TypedConfig
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

    _topt: Optional[TOTP] = None  # lazily loaded when calling .totp or .generate()

    def __repr__(self) -> str:
        return f"<2fas '{self.name}'>"

    @property
    def totp(self) -> TOTP:
        if not self._topt:
            self._topt = TOTP(self.secret)
        return self._topt

    def generate(self) -> str:
        return self.totp.now()
