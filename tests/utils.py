import ast
import os
import subprocess
import sys
import tempfile
from textwrap import dedent
from typing import List

from turms.run import write_code_to_file

DIR_NAME = os.path.dirname(os.path.realpath(__file__))


def build_relative_glob(path):
    return DIR_NAME + path



class ExecuteError(Exception):
    pass


mocks_code = """
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


def query(model: Type[T], variables) -> T:
    return model(variables)  # pragma: nocover


async def aquery(model: Type[T], variables) -> T:
    return model(variables)  # pragma: nocover


def subscribe(model: Type[T], variables) -> T:
    yield model(variables)  # pragma: nocover
    yield model(variables)  # pragma: nocover


async def asubscribe(model: Type[T], variables) -> T:
    yield model(variables)  # pragma: nocover
    yield model(variables)  # pragma: nocover


class ExtraArguments(BaseModel):
    extra: Optional[str]


class ExtraOnOperations(BaseModel):
    extra: Optional[str]


class ExtraArg(BaseModel):
    extra: Optional[str]

"""


def parse_to_code(tree: List[ast.AST]) -> str:
    md = ast.Module(body=tree, type_ignores=[])
    return ast.unparse(ast.fix_missing_locations(md))


def unit_test_with(generated_ast: List[ast.AST], test_string: str):

    added_code = ast.parse(dedent(test_string)).body
    # We need to unparse before otherwise there might be complaints with missing lineno
    parsed_code = parse_to_code(generated_ast + added_code)

    with tempfile.TemporaryDirectory() as tmpdirname:

        filename = write_code_to_file(parsed_code, tmpdirname, "minimal.py")
        write_code_to_file(mocks_code, tmpdirname, "mocks.py")
        s = subprocess.run([sys.executable, filename], capture_output=True)
        if s.returncode == 0:
            return True
        else:
            # If the supbrocess failed we can break out of the sandbox and just return the actual error
            raise ExecuteError(f"Failed with: {s.stderr.decode().strip()} Code: {parsed_code}" )
