"""Small historical-bar expression language, interpreted without eval/exec."""
import ast
import math
import operator
from functools import lru_cache

FIELDS = {'open', 'high', 'low', 'close', 'volume'}
FUNCTIONS = {'sma', 'std', 'lag', 'ret'}
ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv}
COMPARE = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt,
           ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


@lru_cache(maxsize=128)
def validate_rule(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        raise ValueError('strategy expression requires 1..2000 characters')
    try:
        root = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('invalid strategy expression') from exc
    if sum(1 for _ in ast.walk(root)) > 120:
        raise ValueError('strategy expression exceeds node budget')
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
               ast.BinOp, ast.Compare, ast.Name, ast.Load, ast.Constant, ast.Call,
               *ARITHMETIC, *COMPARE)
    for node in ast.walk(root):
        if not isinstance(node, allowed):
            raise ValueError('unsupported strategy expression node')
        if isinstance(node, ast.Name) and node.id not in FIELDS | FUNCTIONS:
            raise ValueError('unknown strategy name')
        if isinstance(node, ast.Constant) and (type(node.value) not in (int, float, bool)
                                               or not math.isfinite(node.value) or abs(node.value) > 1e9):
            raise ValueError('invalid strategy constant')
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS
                    or node.keywords or len(node.args) != 2
                    or not isinstance(node.args[0], ast.Name) or node.args[0].id not in FIELDS
                    or not isinstance(node.args[1], ast.Constant)
                    or type(node.args[1].value) is not int or not 1 <= node.args[1].value <= 252):
                raise ValueError('strategy functions require a price field and period 1..252')
    return root


def evaluate_rule(expression, history):
    root = validate_rule(expression)
    if not history:
        return False

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return float(history[-1][node.id]) if node.id in FIELDS else None
        if isinstance(node, ast.Call):
            field, n = node.args[0].id, node.args[1].value
            name = node.func.id
            needed = n+1 if name in {'lag', 'ret'} else n
            if len(history) < needed:
                return None
            samples = [float(b[field]) for b in history[-needed:]]
            if name == 'lag':
                return samples[0]
            if name == 'ret':
                return samples[-1]/samples[0]-1 if samples[0] else None
            mean = sum(samples)/n
            return mean if name == 'sma' else math.sqrt(sum((x-mean)**2 for x in samples)/n)
        if isinstance(node, ast.UnaryOp):
            x = value(node.operand)
            return None if x is None else (not x if isinstance(node.op, ast.Not) else -x)
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if left is None or right is None or isinstance(node.op, ast.Div) and right == 0:
                return None
            result = ARITHMETIC[type(node.op)](left, right)
            return result if math.isfinite(result) else None
        if isinstance(node, ast.Compare):
            left = value(node.left)
            for operation, target in zip(node.ops, node.comparators):
                right = value(target)
                if left is None or right is None:
                    return None
                if not COMPARE[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [value(child) for child in node.values]
            if any(x is None for x in values):
                return None
            return all(values) if isinstance(node.op, ast.And) else any(values)
        raise ValueError('invalid strategy expression')

    result = value(root.body)
    return bool(result) if result is not None else False
