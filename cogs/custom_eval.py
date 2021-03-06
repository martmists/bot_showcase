import contextlib
import inspect
import re
from io import StringIO
from textwrap import indent
from traceback import format_exc
from typing import Tuple, Any, Union, Optional

import discord
from discord import Embed
from discord.ext.commands import Context, command, Bot

from core.formatters import EvalFormatter, SimpleEvalFormatter, IPythonEvalFormatter

EVAL_FMT = """
try:
    with contextlib.redirect_stdout(self.buffer):
{body}
finally:
    self.env.update(locals())
""".strip()


class EvalCog:
    def __init__(self, bot, fmt: Optional[EvalFormatter] = None):
        self.buffer = StringIO()
        self.fmt = fmt or SimpleEvalFormatter()
        self.bot = bot
        self.env = {}
        self.init_env()

    def init_env(self):
        self.env = {
            "bot": self.bot,
            "inspect": inspect,
            "contextlib": contextlib,
            "self": self,
            "discord": discord,
        }

    async def any_eval(self, stmt: str, env: dict) -> Any:
        self.buffer.seek(0)
        lines = [line.strip() for line in stmt.split("\n") if line.strip()]
        stmt = "\n".join(lines)
        self.env.update(env)
        if len(lines) == 1 and not (';' in stmt or re.search(r"[^><!=~+\-\/*%]=[^=]", stmt)):  # make sure there's no assignment
            try:
                compile("_ = " + stmt, "<eval-repl>", "exec", ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                stmt = "_ = " + stmt + "\nif inspect.isawaitable(_):\n    _ = await _\nreturn _"
            except SyntaxError:
                pass

        _code = EVAL_FMT.format(body=indent(stmt, " "*8))

        func = eval(compile(_code, "<eval-repl>", "exec", ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), self.env)

        try:
            res = await func()
        except Exception:
            lines = format_exc().split("\n")
            lines = [lines[0], *lines[3:]]
            self.buffer.write("\n".join(lines))
            res = None

        return res

    def pre_process(self, input_: str, ctx: Context) -> Tuple[str, dict, bool]:
        if input_.strip() in ("exit", "exit()", "quit", "quit()"):
            return self.fmt.exit(input_.strip()), {}, False

        ctx = {
            "message": ctx.message,
            "author": ctx.author,
            "channel": ctx.channel,
            "guild": ctx.guild,
            "ctx": ctx,
            "me": ctx.me
        }

        return input_.strip(), ctx, True

    async def do_eval(self, input_: str, context: Context) -> Union[str, Embed, Tuple[str, Embed]]:
        input_code, env, do_run = self.pre_process(input_, context)
        if do_run:
            out = await self.any_eval(input_code, env)
            self.buffer.seek(0)
            printed = self.buffer.read()
            self.buffer = StringIO()
        else:
            self.init_env()
            return input_code

        return self.fmt.format(input_code, out, printed)

    @command()
    # IMPORTANT: Add IS_OWNER check before using this code!
    async def eval(self, ctx: Context, *, code: str):
        if code.startswith("```py"):
            code = code[5:-3]
        elif code.startswith("`"):
            code = code[1:-1]
        res = await self.do_eval(code, ctx)
        if isinstance(res, str):
            await ctx.send(f"```py\n{res}\n```")
        elif isinstance(res, Embed):
            await ctx.send(embed=res)
        elif isinstance(res, tuple):
            await ctx.send(res[0], embed=res[1])
        # TODO: Add support for attachments


def setup(core: Bot):
    core.add_cog(EvalCog(core))
