from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PURPOSE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class CapabilityResponse(BaseModel):
    phase: str
    available: list[str]
    unavailable: list[str]


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_by: str
    created_at: datetime


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["SELF", "DEPENDENT", "CAREGIVER"] = "DEPENDENT"
    actor_id: str | None = Field(default=None, max_length=120)


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    display_name: str
    role: str
    actor_id: str | None
    created_at: datetime


class AuthorizationCreate(BaseModel):
    member_id: str
    grantee_actor_id: str = Field(min_length=1, max_length=120)
    data_fields: list[str] = Field(min_length=1)
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS"]] = Field(min_length=1)
    purpose: str = Field(pattern=PURPOSE_PATTERN)
    valid_until: datetime


class AuthorizationUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    data_fields: list[str] | None = Field(default=None, min_length=1)
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS"]] | None = Field(
        default=None,
        min_length=1,
    )
    purpose: str | None = Field(default=None, pattern=PURPOSE_PATTERN)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def require_change(self) -> "AuthorizationUpdate":
        if all(
            value is None
            for value in (self.data_fields, self.actions, self.purpose, self.valid_until)
        ):
            raise ValueError("AUTHORIZATION_UPDATE_EMPTY")
        return self


class AuthorizationRevoke(BaseModel):
    expected_version: int = Field(ge=1)


class AuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str
    grantor_actor_id: str
    grantee_actor_id: str
    data_fields: list[str]
    actions: list[str]
    purpose: str
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class AccessAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    authorization_id: str | None
    actor_id: str
    operation: str
    action: str
    data_field: str
    purpose: str | None
    outcome: str
    reason: str | None
    before_version: int | None
    after_version: int | None
    created_at: datetime


class HealthEventCreate(BaseModel):
    member_id: str
    event_type: str = Field(min_length=1, max_length=80)
    source: Literal["MANUAL"] = "MANUAL"
    confirmation_status: Literal["CONFIRMED", "UNCONFIRMED"] = "UNCONFIRMED"
    payload: dict[str, Any] = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class HealthEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str
    event_type: str
    source: str
    confirmation_status: str
    payload: dict[str, Any]
    evidence: dict[str, Any]
    created_by: str
    confirmed_by: str | None
    created_at: datetime


class MemberStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: str
    household_id: str
    state: dict[str, Any]
    last_event_id: str | None
    updated_at: datetime
