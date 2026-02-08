from .turkcell import TurkcellOperator
from .vodafone import VodafoneOperator
from .base_operator import BaseOperator

class OperatorFactory:
    @staticmethod
    def get_operator(operator_name: str) -> BaseOperator:
        """
        Returns the appropriate operator instance.
        """
        op = operator_name.upper()
        if op == "TURKCELL":
            return TurkcellOperator()
        elif op == "VODAFONE":
            return VodafoneOperator()
        else:
            raise ValueError(f"Unknown operator: {operator_name}")
