"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. These mirror the fixture and assertion
structure of tests/test_collection.py.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    set_watchlist_visibility,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """
    Adding a valid film should create a WatchlistEntry in the database.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        # Verify it persisted
        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Deduplication ────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        # Confirm only one entry exists
        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film ─────────────────────────────────────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── Remove ───────────────────────────────────────────────────────────────────

def test_remove_from_watchlist_removes_entry(app, sample_user, sample_film):
    """
    Removing a film that is on the watchlist should delete the entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert remove_from_watchlist(user_id=sample_user, film_id=sample_film) is True

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 0


def test_remove_from_watchlist_not_present_raises(app, sample_user, sample_film):
    """
    Edge case: removing a film that was never added should raise
    NotInWatchlistError rather than silently succeeding. This guards against a
    caller assuming a delete happened when nothing was on the list.
    """
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)


# ── Visibility toggle ────────────────────────────────────────────────────────

def test_set_watchlist_visibility_updates_public_flag(app, sample_user, sample_film):
    """
    Entries are private by default; set_watchlist_visibility(public=True) should
    flip the entry to public, and public=False should flip it back.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)
        assert entry.public is False  # private by default

        updated = set_watchlist_visibility(
            user_id=sample_user, film_id=sample_film, public=True
        )
        assert updated.public is True

        updated = set_watchlist_visibility(
            user_id=sample_user, film_id=sample_film, public=False
        )
        assert updated.public is False


def test_set_watchlist_visibility_not_present_raises(app, sample_user, sample_film):
    """
    Setting visibility on a film that isn't on the watchlist should raise
    NotInWatchlistError.
    """
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            set_watchlist_visibility(
                user_id=sample_user, film_id=sample_film, public=True
            )


# ── Route-level error handling (add endpoint) ────────────────────────────────
# These trace the full request→response cycle to confirm the route maps service
# exceptions to HTTP status codes (not unhandled 500s), mirroring collection.py.

def test_add_film_route_returns_201(app, sample_user, sample_film):
    """Adding a valid film via POST returns 201."""
    client = app.test_client()
    resp = client.post(
        f"/watchlist/{sample_user}/add", json={"film_id": sample_film}
    )
    assert resp.status_code == 201


def test_add_film_route_nonexistent_returns_404(app, sample_user):
    """A nonexistent film_id returns 404, not a 500 from an unhandled exception."""
    client = app.test_client()
    resp = client.post(
        f"/watchlist/{sample_user}/add",
        json={"film_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


def test_add_film_route_duplicate_returns_409(app, sample_user, sample_film):
    """Adding the same film twice returns 409 Conflict, not a 500."""
    client = app.test_client()
    client.post(f"/watchlist/{sample_user}/add", json={"film_id": sample_film})
    resp = client.post(
        f"/watchlist/{sample_user}/add", json={"film_id": sample_film}
    )
    assert resp.status_code == 409
