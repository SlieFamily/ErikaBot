"""DSH diagnostics. Default is read-only; --smoke creates one isolated model turn."""
import argparse
import asyncio
import importlib
import logging
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("_agent_chat_diagnostics")
package.__path__ = [str(ROOT / "src/plugins/agent_chat")]
sys.modules[package.__name__] = package
load_config = importlib.import_module(package.__name__ + ".config").load_config
dsh = importlib.import_module(package.__name__ + ".dsh")


async def check(args):
    client = dsh.DshClient(load_config(private_file=args.env_file))
    sid = None
    try:
        fingerprint = await client.policy()
        print("PASS: authenticated; safe preset composition verified (" + fingerprint[:12] + ")")
        if args.smoke:
            sid = await client.create_session()
            text = await client.reply(sid, "QQ_CHAT_EVENT diagnostic\n这是独立连通性测试。请只回复：连接成功。不要调用工具。")
            if not text.strip():
                raise dsh.BridgeError("empty_smoke_reply")
            print("PASS: isolated session, prompt correlation and completed text reply; no QQ send")
        else:
            print("Read-only check finished. Use --smoke to test a new session and one paid model turn.")
    finally:
        try:
            if sid:
                await asyncio.wait_for(client.stop(sid), 10)
        finally:
            await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.agent_chat")
    parser.add_argument("--smoke", action="store_true", help="Create one diagnostic DSH session and call its model once")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        asyncio.run(check(args))
    except dsh.BridgeError as error:
        print("FAIL: " + str(error)); sys.exit(1)
    except Exception:
        # Do not print validation inputs, remote messages, credentials or response bodies.
        print("FAIL: configuration_or_protocol_error; check configuration and DSH version"); sys.exit(1)
