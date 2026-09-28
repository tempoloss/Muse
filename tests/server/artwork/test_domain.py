from muse.artwork.domain import artist_key


def test_artist_images_keep_the_sha1_file_names_of_the_existing_cache() -> None:
    assert artist_key("Sable Pylon") == "6b70d9edac896b8cf3d7a2bff88f4be8dbbce45d"
