import anyio
import httpx
from dishka import Provider, Scope, provide

from muse.activity.domain import LikeRepository, PlayRepository
from muse.activity.infra.sql import SqlLikes, SqlPlays
from muse.activity.service import Likes, Plays
from muse.artwork.domain import ArtworkFiles, ArtworkLibrary, ArtworkStores
from muse.artwork.infra.files import LocalArtworkFiles
from muse.artwork.infra.sql import SqlArtworkLibrary
from muse.artwork.infra.stores import OnlineStores
from muse.artwork.service import Artwork
from muse.catalog.domain import (
    CatalogQueries,
    LibraryRoot,
    LibraryState,
    PlaylistSource,
    TrackStorage,
)
from muse.catalog.infra.files import TrackFiles
from muse.catalog.infra.library import LibraryFiles
from muse.catalog.infra.playlists import PlaylistFiles
from muse.catalog.infra.sql import SqlCatalog
from muse.catalog.service import Catalog
from muse.identity.domain import SessionStore
from muse.identity.infra.sql import SqlSessions
from muse.identity.service import LoginService, SessionService
from muse.settings import Settings


class ContextsProvider(Provider):
    scope = Scope.REQUEST

    sessions = provide(SqlSessions, provides=SessionStore)
    login = provide(LoginService)
    session = provide(SessionService)

    catalog_queries = provide(SqlCatalog, provides=CatalogQueries, scope=Scope.APP)
    catalog = provide(Catalog, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def library(self, settings: Settings) -> LibraryState:
        paths = settings.paths
        return LibraryFiles(paths.catalog_db, paths.playlists_dir, paths.covers_dir)

    @provide(scope=Scope.APP)
    def playlists(self, settings: Settings) -> PlaylistSource:
        return PlaylistFiles(settings.paths.playlists_dir)

    @provide(scope=Scope.APP)
    def library_root(self, settings: Settings) -> LibraryRoot:
        return LibraryRoot.at(settings.paths.library_dir)

    @provide(scope=Scope.APP)
    def track_storage(self, settings: Settings, root: LibraryRoot) -> TrackStorage:
        return TrackFiles(settings.paths.library_dir, root)

    artwork_library = provide(SqlArtworkLibrary, provides=ArtworkLibrary, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def artwork_files(self, settings: Settings) -> ArtworkFiles:
        paths = settings.paths
        return LocalArtworkFiles(paths.covers_dir, paths.artists_dir, paths.thumbs_dir)

    @provide(scope=Scope.APP)
    def artwork_stores(self, client: httpx.AsyncClient) -> ArtworkStores:
        return OnlineStores(client, anyio.sleep)

    @provide(scope=Scope.APP)
    def artwork(
        self,
        catalog: Catalog,
        library: ArtworkLibrary,
        files: ArtworkFiles,
        stores: ArtworkStores,
    ) -> Artwork:
        return Artwork(catalog, library, files, stores, anyio.sleep)

    play_store = provide(SqlPlays, provides=PlayRepository)
    like_store = provide(SqlLikes, provides=LikeRepository)
    plays = provide(Plays)
    likes = provide(Likes)
