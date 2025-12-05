import sqlalchemy
import yaml
from pydantic import BaseModel, ValidationError
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session


class SampleModel(BaseModel):
    name: str
    level: int


def test_pyyaml_can_parse_basic_yaml():
    sample_yaml = """
    user:
      name: Kyr Tester
      level: 3
    """

    loaded = yaml.safe_load(sample_yaml)

    assert loaded["user"]["name"] == "Kyr Tester"
    assert loaded["user"]["level"] == 3


def test_pydantic_validates_and_coerces_types():
    payload = {"name": "kyr apprentice", "level": "5"}
    model = SampleModel(**payload)

    assert model.name == "kyr apprentice"
    assert model.level == 5

    with pytest.raises(ValidationError):
        SampleModel(name="kyr apprentice", level="not-a-number")


def test_sqlalchemy_can_roundtrip_data():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    heroes = Table(
        "heroes",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("level", Integer, nullable=False),
    )
    metadata.create_all(engine)

    with Session(engine) as session:
        session.execute(heroes.insert().values(name="Tashanna", level=42))
        session.commit()

        result = session.execute(sqlalchemy.select(heroes.c.name, heroes.c.level)).one()

    assert result == ("Tashanna", 42)
