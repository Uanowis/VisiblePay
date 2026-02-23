from typing import Type
from .base_operator import BaseOperator
# Import implementations here as they are created
# from .turkcell import TurkcellOperator 

class OperatorFactory:
    """
    Factory class to return the correct operator implementation.
    """
    
    _operators = {}

    @classmethod
    def register(cls, name: str, operator_cls: Type[BaseOperator]):
        """
        Register a new operator implementation.
        """
        cls._operators[name.lower()] = operator_cls

    @classmethod
    def get_operator(cls, name: str, page, card=None) -> BaseOperator:
        """
        Get an instance of the requested operator.
        """
        operator_cls = cls._operators.get(name.lower())
        if not operator_cls:
            raise ValueError(f"Operator '{name}' not found or not registered.")
        
        return operator_cls(page, card)

# Pre-register known operators (to be uncommented as implemented)
# OperatorFactory.register('turkcell', TurkcellOperator)
# OperatorFactory.register('vodafone', VodafoneOperator)
