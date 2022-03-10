from typing import List, Optional
from pathlib import Path

import json
import typer

import asyncio
import aiohttp
import aiofiles

app = typer.Typer()

asset_type_to_extension = {
    1: "png",  # Image
    3: "mp3",  # Audio
    5: "lua",  # Lua
    7: "txt",  # Text
    9: "rbxl",  # Place
    10: "rbxm"  # Model
}


async def get_asset_information(session: aiohttp.ClientSession, asset_ids: List[int]):
    chunk_size = 50
    id_chunks = [asset_ids[i:i+chunk_size] for i in range(0, len(asset_ids), chunk_size)]
    results = {}

    for id_chunk in id_chunks:
        develop_response = await session.get(
            url="https://develop.roblox.com/v1/assets",
            params={
                "assetIds": id_chunk
            }
        )
        develop_response.raise_for_status()
        for asset_data in (await develop_response.json())["data"]:
            results[asset_data["id"]] = asset_data

    return results


async def get_asset_contents(session: aiohttp.ClientSession, asset_id: int):
    response = await session.get(
        url="https://assetdelivery.roblox.com/v1/asset",
        params={
            "id": asset_id
        },
        allow_redirects=True
    )
    response.raise_for_status()

    return await response.content.read()


async def download_asset_to_path(session: aiohttp.ClientSession, asset_id: int, asset_path: Path):
    content = await get_asset_contents(session, asset_id)

    async with aiofiles.open(asset_path, "wb") as file:
        file.write(content)


async def main(
        path: Path,
        asset_ids: List[int],
        token: Optional[str] = None
):
    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "Roblox/WinInet",
            "Roblox-Browser-Asset-Request": "true"
        },
        cookies={
            ".ROBLOSECURITY": token
        }
    ) as session:
        typer.echo("Fetching asset information...")
        asset_infos = await get_asset_information(session, asset_ids)
        result_metadata = []

        coroutines = []
        for asset_id in asset_ids:
            asset_info = asset_infos[asset_id]
            asset_extension = asset_type_to_extension.get(asset_info["typeId"], "bin")
            asset_filename = f"{asset_id}.{asset_extension}"
            asset_path = path / asset_filename
            result_metadata.append({
                "name": asset_info["name"],
                "id": asset_info["id"],
                "filename": asset_filename,
                "type_id": asset_info["typeId"],
            })

            coroutines.append(download_asset_to_path(
                session=session,
                asset_id=asset_id,
                asset_path=asset_path
            ))

        results = []
        with typer.progressbar(
                iterable=coroutines,
                length=len(coroutines),
                label="Downloading..."
        ) as progress:
            for coroutine in progress:
                try:
                    results.append((True, await coroutine))
                except Exception as exception:
                    results.append((False, exception))

        success_count = 0
        fail_count = 0
        for i, result in enumerate(results):
            if result[0]:
                success_count += 1
            else:
                fail_count += 1

            result_metadata[i]["success"] = result[0]

        typer.echo(f"{len(results)} assets downloaded. {success_count} succeeded, {fail_count} failed.")

        async with aiofiles.open(path / "assets.json", "w") as file:
            await file.write(json.dumps({
                "assets": result_metadata
            }, indent=2))


@app.command()
def root(
        path: Path = typer.Option(
            default=...,
            help="A folder to download assets to.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True
        ),
        asset_ids: str = typer.Option(..., help="A comma-separated list of asset IDs to dump."),
        token: Optional[str] = typer.Option(None, help="A .ROBLOSECURITY token.")
):
    assert path.exists(), "Path does not exist."

    asset_ids = [int(x.strip()) for x in asset_ids.split(",")]
    assert len(asset_ids), "No asset IDs specified."

    asyncio.get_event_loop().run_until_complete(main(
        path=path,
        asset_ids=asset_ids,
        token=token
    ))


if __name__ == '__main__':
    app()
