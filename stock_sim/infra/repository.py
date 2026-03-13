# file: infra/repository.py
# python
from typing import TypeVar, Generic, Type, Any, Sequence
from sqlalchemy.orm import Session

T = TypeVar("T")

class Repository(Generic[T]):
    def __init__(self, model: Type[T], session: Session):
        self.model = model
        self.session = session

    def get(self, pk: Any) -> T | None:
        return self.session.get(self.model, pk)

    def add(self, obj: T):
        self.session.add(obj)

    def list(self, **filters) -> Sequence[T]:
        return self.session.query(self.model).filter_by(**filters).all()