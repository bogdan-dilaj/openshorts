import asyncio
import io
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as openshorts


def make_video() -> UploadFile:
    return UploadFile(
        filename="clip.mp4",
        file=io.BytesIO(b"test-video"),
        headers=Headers({"content-type": "video/mp4"}),
    )


def vendor_result(platforms):
    return {
        "success": True,
        "status": "pending",
        "message": "Accepted",
        "scheduled": False,
        "request_id": "request-123",
        "job_id": None,
        "requested_platforms": platforms,
        "platform_results": [
            {"platform": platform, "success": None, "status": "pending"}
            for platform in platforms
        ],
        "success_count": 0,
        "failure_count": 0,
        "pending_count": len(platforms),
    }


async def run_tests() -> None:
    platforms = ["instagram", "tiktok", "youtube"]
    cta = 'Kommentiere "Video" und wir senden dir den Link zum Podcast zu'

    with (
        patch.object(openshorts, "_send_upload_post_video", return_value=vendor_result(platforms)) as send_upload,
        patch.object(openshorts, "_notify_podcast_dm_relay", new=AsyncMock(return_value={"success": True})) as notify_relay,
    ):
        result = await openshorts.post_uploaded_video_to_socials(
            video=make_video(),
            api_key="test-key",
            user_id="anna",
            platforms=json.dumps(platforms),
            title="Normal title",
            description="Normal caption",
            first_comment="Normal first comment",
            scheduled_date=None,
            timezone="UTC",
            instagram_share_mode="CUSTOM",
            tiktok_post_mode="DIRECT_POST",
            tiktok_is_aigc=False,
            facebook_page_id=None,
            pinterest_board_id=None,
            language="de",
            podcast_dm_enabled=True,
            podcast_dm_link_url="https://example.com/podcast",
            podcast_dm_keyword="Video",
            podcast_dm_relay_url="https://relay.example.com/relay.php",
            podcast_dm_relay_password="secret",
        )

        payload = send_upload.call_args.kwargs["data_payload"]
        assert payload["title"] == "Normal title"
        assert payload["first_comment"] == "Normal first comment"
        assert payload["instagram_title"] == f"{cta}\n\nNormal caption"
        assert payload["instagram_first_comment"] == f"{cta}\n\nNormal first comment"
        assert payload["tiktok_title"] == "Normal caption"
        assert payload["youtube_title"] == "Normal title"
        assert payload["youtube_description"] == "Normal caption"
        assert payload["youtube_first_comment"] == "Normal first comment"

        relay_call = notify_relay.await_args.kwargs
        assert relay_call["requested_platforms"] == platforms
        assert relay_call["campaign"]["link_url"] == "https://example.com/podcast"
        assert relay_call["status_payload"]["request_settings"]["instagram_first_comment"] == f"{cta}\n\nNormal first comment"
        assert result["podcast_dm_relay"]["success"] is True

    with (
        patch.object(openshorts, "_send_upload_post_video") as send_upload,
        patch.object(openshorts, "_notify_podcast_dm_relay", new=AsyncMock()) as notify_relay,
    ):
        try:
            await openshorts.post_uploaded_video_to_socials(
                video=make_video(),
                api_key="test-key",
                user_id="anna",
                platforms=json.dumps(["instagram"]),
                title="Normal title",
                description="Normal caption",
                first_comment="",
                scheduled_date=None,
                timezone="UTC",
                instagram_share_mode="CUSTOM",
                tiktok_post_mode="DIRECT_POST",
                tiktok_is_aigc=False,
                facebook_page_id=None,
                pinterest_board_id=None,
                language=None,
                podcast_dm_enabled=True,
                podcast_dm_link_url="not a valid link",
                podcast_dm_keyword="Video",
                podcast_dm_relay_url="https://relay.example.com/relay.php",
                podcast_dm_relay_password="secret",
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("An invalid DM destination must fail before upload.")

        send_upload.assert_not_called()
        notify_relay.assert_not_awaited()

    print("Direct-upload Instagram DM tests passed.")


if __name__ == "__main__":
    asyncio.run(run_tests())
