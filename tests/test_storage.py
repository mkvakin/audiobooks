import pytest
import shutil
from pathlib import Path
from app.storage import StorageConfig, LocalStorageAdapter, create_storage_adapter
from app.storage.storage_ops import (
    atomic_write_storage,
    verify_mp3_storage,
    is_chapter_completed_storage,
    cleanup_parts_storage,
    get_temp_local_path
)

@pytest.fixture
def temp_storage_dir(tmp_path):
    """Fixture for a temporary storage directory."""
    storage_path = tmp_path / "audiobooks_test"
    storage_path.mkdir()
    yield storage_path
    if storage_path.exists():
        shutil.rmtree(storage_path)

@pytest.fixture
def local_storage(temp_storage_dir):
    """Fixture for LocalStorageAdapter."""
    config = StorageConfig(base_dir=temp_storage_dir)
    return LocalStorageAdapter(config)

class TestLocalStorageAdapter:
    def test_write_and_read_bytes(self, local_storage):
        content = b"test content"
        path = "test_file.bin"
        local_storage.write_bytes(path, content)
        
        assert local_storage.exists(path)
        assert local_storage.read_bytes(path) == content
        
    def test_write_and_read_text(self, local_storage):
        content = "test text"
        path = "test_file.txt"
        local_storage.write_text(path, content)
        
        assert local_storage.exists(path)
        assert local_storage.read_text(path) == content
        
    def test_delete(self, local_storage):
        path = "delete_me.txt"
        local_storage.write_text(path, "content")
        assert local_storage.exists(path)
        
        local_storage.delete(path)
        assert not local_storage.exists(path)
        
    def test_list_files(self, local_storage):
        local_storage.write_text("dir1/file1.txt", "content")
        local_storage.write_text("dir1/file2.txt", "content")
        local_storage.write_text("dir2/file3.txt", "content")
        
        files = local_storage.list_files("dir1")
        assert len(files) == 2
        assert "dir1/file1.txt" in files
        assert "dir1/file2.txt" in files
        
    def test_mkdir(self, local_storage, temp_storage_dir):
        local_storage.mkdir("new_dir/sub_dir")
        assert (temp_storage_dir / "new_dir" / "sub_dir").is_dir()

    def test_get_local_path(self, local_storage, temp_storage_dir):
        path = "some_file.txt"
        local_path = local_storage.get_local_path(path)
        assert local_path == temp_storage_dir / path

class TestStorageOps:
    def test_atomic_write_storage(self, local_storage):
        path = "atomic.bin"
        content = b"atomic content"
        atomic_write_storage(local_storage, path, content)
        assert local_storage.read_bytes(path) == content
        
    def test_verify_mp3_storage_valid_id3(self, local_storage):
        path = "test.mp3"
        # Mocking a minimal ID3 header
        content = b"ID3" + b"\x00" * 125
        local_storage.write_bytes(path, content)
        assert verify_mp3_storage(local_storage, path) is True
        
    def test_verify_mp3_storage_valid_sync(self, local_storage):
        path = "test.mp3"
        # Mocking a minimal MP3 sync frame
        content = b"\xFF\xFB" + b"\x00" * 126
        local_storage.write_bytes(path, content)
        assert verify_mp3_storage(local_storage, path) is True
        
    def test_verify_mp3_storage_invalid(self, local_storage):
        path = "invalid.mp3"
        local_storage.write_bytes(path, b"not an mp3" * 20)
        assert verify_mp3_storage(local_storage, path) is False
        
    def test_is_chapter_completed_storage(self, local_storage):
        book_dir = "test_book"
        chapter_num = 1
        chapter_title = "Intro"
        # The filename generation depends on get_chapter_final_path
        from app.core.atomic_ops import get_chapter_final_path
        expected_filename = get_chapter_final_path(Path("."), chapter_num, chapter_title).name
        storage_path = f"{book_dir}/{expected_filename}"
        
        assert is_chapter_completed_storage(local_storage, book_dir, chapter_num, chapter_title) is False
        
        # Create a valid-looking file
        content = b"ID3" + b"\x00" * 130
        local_storage.write_bytes(storage_path, content)
        
        assert is_chapter_completed_storage(local_storage, book_dir, chapter_num, chapter_title) is True
        
    def test_cleanup_parts_storage(self, local_storage):
        parts_dir = "test_book/parts"
        local_storage.write_bytes(f"{parts_dir}/chapter_01_part_001_of_001_Title.mp3", b"data")
        local_storage.write_bytes(f"{parts_dir}/chapter_01_part_002_of_002_Title.mp3", b"data")
        local_storage.write_bytes(f"{parts_dir}/other.txt", b"data")
        
        count = cleanup_parts_storage(local_storage, parts_dir)
        assert count == 2
        assert not local_storage.exists(f"{parts_dir}/chapter_01_part_001_of_001_Title.mp3")
        assert local_storage.exists(f"{parts_dir}/other.txt")
        
    def test_get_temp_local_path_local(self, local_storage, temp_storage_dir):
        path = "local.txt"
        local_storage.write_text(path, "content")
        local_path = get_temp_local_path(local_storage, path)
        assert local_path == temp_storage_dir / path
        assert local_path.exists()
