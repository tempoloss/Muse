from dishka import Provider, Scope, provide

from muse.catalog.domain import CatalogQueries, LibraryState
from muse.catalog.infra.library import LibraryFiles
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
