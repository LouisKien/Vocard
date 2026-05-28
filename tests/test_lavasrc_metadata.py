from __future__ import annotations

from voicelink.objects import Playlist, Track
from voicelink.pool import Node
from voicelink.transformer import DataWriter, decode, encode


def encode_lavasrc_fields(writer: DataWriter, track: dict[str, object]) -> None:
    writer.write_nullable_utf(track.get("albumName"))
    writer.write_nullable_utf(track.get("albumUrl"))
    writer.write_nullable_utf(track.get("artistUrl"))
    writer.write_nullable_utf(track.get("artistArtworkUrl"))
    writer.write_nullable_utf(track.get("previewUrl"))
    writer.write_boolean(bool(track.get("isPreview")))


def test_decode_preserves_lavasrc_fields_with_backward_compatible_aliases() -> None:
    encoded = encode(
        {
            "title": "Song",
            "author": "Artist",
            "length": 123456,
            "identifier": "spotify-track-id",
            "isStream": False,
            "uri": "https://open.spotify.com/track/spotify-track-id",
            "artworkUrl": "https://cdn.example/artwork.jpg",
            "isrc": "ABC123456789",
            "sourceName": "spotify",
            "position": 0,
            "albumName": "Album",
            "albumUrl": "https://open.spotify.com/album/album-id",
            "artistUrl": "https://open.spotify.com/artist/artist-id",
            "artistArtworkUrl": "https://cdn.example/artist.jpg",
            "previewUrl": "https://cdn.example/preview.mp3",
            "isPreview": True,
        },
        source_encoders={"spotify": encode_lavasrc_fields},
    )

    decoded = decode(encoded)

    assert decoded["albumName"] == "Album"
    assert decoded["album_name"] == "Album"
    assert decoded["albumUrl"] == "https://open.spotify.com/album/album-id"
    assert decoded["artistUrl"] == "https://open.spotify.com/artist/artist-id"
    assert decoded["artist_url"] == "https://open.spotify.com/artist/artist-id"
    assert decoded["artistArtworkUrl"] == "https://cdn.example/artist.jpg"
    assert decoded["artistArtUrl"] == "https://cdn.example/artist.jpg"
    assert decoded["previewUrl"] == "https://cdn.example/preview.mp3"
    assert decoded["isPreview"] is True
    assert decoded["is_preview"] is True


def test_track_prefers_lavasrc_artwork_fallback_aliases() -> None:
    track = Track(
        info={
            "identifier": "spotify-track-id",
            "title": "Song",
            "author": "Artist",
            "uri": "https://open.spotify.com/track/spotify-track-id",
            "sourceName": "spotify",
            "length": 123456,
            "albumArtUrl": "https://cdn.example/album-art.jpg",
        },
        requester=None,
    )

    assert track.thumbnail == "https://cdn.example/album-art.jpg"


def test_playlist_exposes_plugin_info_metadata() -> None:
    playlist = Playlist(
        playlist_info={
            "name": "Spotify Playlist",
            "selectedTrack": -1,
            "type": "playlist",
            "url": "https://open.spotify.com/playlist/playlist-id",
            "artworkUrl": "https://cdn.example/playlist.jpg",
            "author": "Curator",
            "trackCount": 2,
        },
        tracks=[
            {
                "encoded": "track-1",
                "info": {
                    "identifier": "track-1",
                    "title": "Song 1",
                    "author": "Artist 1",
                    "uri": "https://open.spotify.com/track/track-1",
                    "sourceName": "spotify",
                    "length": 1000,
                    "artworkUrl": "https://cdn.example/track-1.jpg",
                },
            },
            {
                "encoded": "track-2",
                "info": {
                    "identifier": "track-2",
                    "title": "Song 2",
                    "author": "Artist 2",
                    "uri": "https://open.spotify.com/track/track-2",
                    "sourceName": "spotify",
                    "length": 1000,
                    "artworkUrl": "https://cdn.example/track-2.jpg",
                },
            },
        ],
        requester=None,
    )

    assert playlist.name == "Spotify Playlist"
    assert playlist.uri == "https://open.spotify.com/playlist/playlist-id"
    assert playlist.thumbnail == "https://cdn.example/playlist.jpg"
    assert playlist.author == "Curator"
    assert playlist.type == "playlist"
    assert playlist.track_count == 2


def test_spotify_urls_select_lavasrc_api_mode() -> None:
    assert Node._spotify_partner_api_for_query(
        "https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc"
    ) is True
    assert Node._spotify_partner_api_for_query(
        "https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=abc"
    ) is False
    assert Node._spotify_partner_api_for_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is None


def test_track_query_is_trimmed_before_lavalink_loading() -> None:
    assert Node._normalize_query(" https://youtu.be/YGzQTjvrC2o?si=abc ") == "https://youtu.be/YGzQTjvrC2o?si=abc"
