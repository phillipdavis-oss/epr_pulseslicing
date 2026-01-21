import asyncio
import telnetlib3

def login_command(MAC):
    print(f"$LOGIN VR{MAC.replace(':', '')[-6:]}\n")
    print("logging in...")
    return f"$LOGIN VR{MAC.replace(':', '')[-6:]}\n"


async def send_receive(reader, writer, command) -> str:
    try:
        async with asyncio.timeout(3):
            writer.write(command)
            await writer.drain()
            resp = await reader.read(20)
            return resp
    except asyncio.TimeoutError:
    # except IndexError:
        return "Could not connect to the laser"


async def create_reader_writer(host, port, mac):
    try:
        async with asyncio.timeout(3):
            reader, writer = await telnetlib3.open_connection(
                host, port, encoding="ascii",
            )
    except (ConnectionRefusedError, asyncio.TimeoutError):
    # except IndexError:
        return None, None, "Could not connect to the laser"
    return reader, writer, "Initialized"