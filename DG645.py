import socket
import asyncio
import functools
import inspect

IP_ADDRESS = "192.168.103.164"
PORT = 5025


def no_socket_handler(func) -> object:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            if inspect.iscoroutinefunction(func):
                res = await func(*args, **kwargs)
            else:
                res = func(*args, **kwargs)
        except socket.error as e:
            res = f"Failed to connect to {IP_ADDRESS}:{PORT}.".encode("utf-8")
        finally:
            if isinstance(res, tuple) or isinstance(res, list):
                return *res,
            return res
    return wrapper


async def test():
    reader, writer, resp = await connect(ip=IP_ADDRESS, port=PORT)
    resp = await send_receive(reader, writer, "DLAY?2\n")
    await close(writer)



@no_socket_handler
async def connect(ip=IP_ADDRESS, port=PORT) -> None:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1)

        resp = f"Attempting to connect to DG645 at {ip}:{port}\n"
    except asyncio.TimeoutError:
        return None, None, f"Connection to DG645 at {ip}:{port} timed out.\n"

    return reader, writer, resp


@no_socket_handler
async def send_receive(reader, writer, command):
    if not command.endswith("\n"):
        command += "\n"
    writer.write(command.encode("utf-8"))
    await writer.drain()
    resp = await asyncio.wait_for(reader.read(1024), timeout=1)
    print(resp, resp.decode("ascii"))
    # return resp.decode("ascii")
    return ""

@no_socket_handler
async def close(writer):
    writer.close()
    await writer.wait_closed()
    return "Closed.\n"


if __name__ == "__main__":
    # loop = asyncio.new_event_loop()
    # loop.run_until_complete(test())
    asyncio.run(test())
