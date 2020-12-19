"""Clase AluRepo para manejar los repositorios individuales y grupales.
"""

import base64
import io
import pathlib
import re
import sys
import tempfile

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import git  # type: ignore
import github

from git.objects.fun import traverse_tree_recursive  # type: ignore
from git.util import stream_copy  # type: ignore
from github import InputGitTreeElement
from github.GitTree import GitTree as GithubTree
from github.Repository import Repository as GithubRepo


# Se saca el emoji de la sincronización porque ya hay checkruns que indican el resultado
EMOJI_REGEX = re.compile("^:(heavy_check_mark|x): ")


class AluRepo:
    """Clase para sincronizar un repo de alumne.
    """

    def __init__(self, repo_full: str, *, auth_token: str):
        self.gh_repo: Optional[GithubRepo] = None  # TODO: Make this a @property.
        self.repo_full = repo_full
        self.auth_token = auth_token

    @property
    def url(self):
        return f"https://github.com/{self.repo_full}"

    def ensure_exists(self, *, skel_repo: str = None):
        """Crea el repositorio en Github, si no existe aún.

        Si el repositorio ya existe, no se hace nada. Si no existe, se lo
        crea y se le inicializa con los contenidos de `skel_repo`.

        Raises:
          github.GithubException si no se pudo crear el repositorio.
        """
        gh = github.Github(self.auth_token)
        try:
            self.gh_repo = gh.get_repo(self.repo_full)
        except github.UnknownObjectException:
            pass
        else:
            return

        owner, name = self.repo_full.split("/", 1)
        organization = gh.get_organization(owner)

        # TODO: get all settings from repos.yml (incl. skel_repo & team_name).
        new_repo = organization.create_repo(
            name,
            private=True,
            has_wiki=False,
            has_projects=False,
            has_downloads=False,
            allow_squash_merge=False,
            allow_rebase_merge=False,
            delete_branch_on_merge=False,  # type: ignore
        )

        # Hacer push de todas las ramas del esqueleto.
        if skel_repo is not None:
            skel_repo = f"git@github.com:{skel_repo}"
            repo_full = f"git@github.com:{self.repo_full}"
            with tempfile.TemporaryDirectory() as tmpdir:
                git.Repo.clone_from(skel_repo, tmpdir)
                git.cmd.Git(working_dir=tmpdir).push(
                    [repo_full, "refs/remotes/origin/*:refs/heads/*"]
                )

        # Dar permiso a los docentes.
        try:
            team = organization.get_team_by_slug("algorw-20b")
        except github.UnknownObjectException:
            pass
        else:
            team.set_repo_permission(new_repo, "admin")

        # TODO: configure branch protections (necesario para cuando se dé permiso para
        # hacer push de manera directa para las entregas, desde Git).

    def sync(
        self,
        entrega_dir: pathlib.Path,
        rama: str,
        ghuser: str,
        checkrun: Optional[Dict] = None,
        *,
        target_subdir: str = None,
    ):
        """Importa una entrega a los repositorios de alumnes.

        Args:
          entrega_dir: ruta en repo externo con los archivos actualizados.
          rama: rama en la que actualizar la entrega.
          ghuser: nombre de cuenta de Github con que crear los commits.
          target_subdir: directorio que se debe actuaizar dentro el repositorio.
              Si no se especifica, se usa el nombre de la rama (usar la cadena
              vacía para actualizar el toplevel).
          checkrun: resultado de la corrección en formato CheckRun de Github, a
              ser asociado con el último commit.

        Raises:
          github.UnknownObjectException si el repositorio no existe.
          github.GithubException si se recibió algún otro error de la API.
        """
        if target_subdir is None:
            target_subdir = rama

        gh = github.Github(self.auth_token)
        repo = self.gh_repo or gh.get_repo(self.repo_full)
        gitref = repo.get_git_ref(f"heads/{rama}")
        prefix_re = re.compile(re.escape(target_subdir.rstrip("/") + "/"))

        # Estado actual del repo.
        cur_sha = gitref.object.sha
        # NOTE: como solo trabajamos en un subdirectorio, se podría limitar el uso
        # de recursive a ese directorio (si trabajáramos con repos muy grandes).
        cur_tree = repo.get_git_tree(cur_sha, recursive=True)
        cur_commit = repo.get_git_commit(cur_sha)

        # Tree de la entrega en master, para manejar borrados.
        baseref = repo.get_git_ref(f"heads/{repo.default_branch}")
        base_tree = repo.get_git_tree(baseref.object.sha, recursive=True)

        # Examinar el repo de entregas para obtener los commits a aplicar.
        entrega_repo = git.Repo(entrega_dir, search_parent_directories=True)
        entrega_relpath = entrega_dir.relative_to(entrega_repo.working_dir).as_posix()
        pending_commits = []
        cur_commit_date = cur_commit.author.date

        # La fecha de la API siempre viene en UTC, pero PyGithub no le asigna
        # timezone, y se interpretaría en zona horaria local por omisión. Ver
        # https://github.com/PyGithub/PyGithub/pull/704.
        cur_commit_date = cur_commit_date.replace(tzinfo=timezone.utc)

        for commit in entrega_repo.iter_commits(paths=[entrega_relpath]):
            if commit.authored_date > cur_commit_date.timestamp():
                pending_commits.append(commit)

        for commit in reversed(pending_commits):
            entrega_tree = commit.tree.join(entrega_relpath)
            tree_contents = tree_to_github(entrega_tree, target_subdir, repo)
            entrega_files = set(tree_contents.keys())
            tree_elements = list(tree_contents.values())
            tree_elements.extend(
                deleted_files(entrega_files, cur_tree, prefix_re, base_tree)
            )
            author_date = datetime.fromtimestamp(commit.authored_date).astimezone()
            author_info = github.InputGitAuthor(
                ghuser, f"{ghuser}@users.noreply.github.com", author_date.isoformat()
            )
            cur_tree = repo.create_git_tree(tree_elements, cur_tree)
            cur_commit = repo.create_git_commit(
                EMOJI_REGEX.sub("", commit.message), cur_tree, [cur_commit], author_info
            )
            # Se necesita obtener el árbol de manera recursiva para tener
            # los contenidos del subdirectorio de la entrega.
            cur_tree = repo.get_git_tree(cur_tree.sha, recursive=True)

        gitref.edit(cur_commit.sha)

        # Crear checkrun si se recibió la salida del corrector.
        # FIXME: esto falla si el auth_token que se nos pasó pertenece a wachenbot
        # (cuenta común) y no a algorw-corr (Github App), porque la API de Checks
        # solo está disponible para apps.
        # TODO: asegurarnos que siempre se nos pasa un auth_token de algorw-corr,
        # o que somos capaces de crearlo acá. (Ver también algo2_sistema_entregas#67).
        if checkrun is not None:
            nombre = checkrun.pop("name", rama)
            try:
                repo.create_check_run(nombre, cur_commit.sha, **checkrun)
            except github.BadCredentialsException as ex:
                print(f"Bad credentials al crear el check-run ({ex})", file=sys.stderr)
            except github.GithubException as ex:
                # BadCredentialsException no funciona por el momento:
                # https://github.com/PyGithub/PyGithub/issues/1794
                if ex.status == 403:
                    print(f"Error al crear el check-run ({ex})", file=sys.stderr)
                else:
                    raise ex from None


def tree_to_github(
    tree: git.Tree, target_subdir: str, gh_repo: GithubRepo
) -> Dict[str, InputGitTreeElement]:
    """Extrae los contenidos de un commit de Git en formato Tree de Github.

    Returns:
      un diccionario donde las claves son rutas en el repo, y los valores
      el InputGitTreeElement que los modifica.
    """
    odb = tree.repo.odb
    target_subdir = target_subdir.rstrip("/") + "/"
    entries = traverse_tree_recursive(odb, tree.binsha, target_subdir)
    contents = {}

    for sha, mode, path in entries:
        # TODO: get exclusion list from repos.yml
        if path.endswith("README.md"):
            continue
        fileobj = io.BytesIO()
        stream_copy(odb.stream(sha), fileobj)
        fileobj.seek(0)
        try:
            text = fileobj.read().decode("utf-8")
            input_elem = InputGitTreeElement(path, f"{mode:o}", "blob", text)
        except UnicodeDecodeError:
            # POST /trees solo permite texto, hay que crear un blob para binario.
            fileobj.seek(0)
            data = base64.b64encode(fileobj.read())
            blob = gh_repo.create_git_blob(data.decode("ascii"), "base64")
            input_elem = InputGitTreeElement(path, f"{mode:o}", "blob", sha=blob.sha)
        finally:
            contents[path] = input_elem

    return contents


def deleted_files(
    new_files: Set[str],
    cur_tree: GithubTree,
    match_re: re.Pattern = None,
    preserve_from: GithubTree = None,
) -> List[InputGitTreeElement]:
    """Calcula los archivos a borrar en el repositorio junto con la entrega.

    Dada una lista que representa los contenidos actuales de la nueva
    entrega, y dado el árbol existente, esta función calcula los archivos
    que deben ser borrados, y los devuelve en una lista. (Para borrar
    un archivo a través de la API de Github, lo que se necesita es un
    InputGitTreeElement con sha=None.)

    La expresión regular `match_re` se usa para filtrar los subdirectorios
    sobre los que procesar los borrados. Si se especifica `preserve_from`,
    nunca se borrarán archivos que estén presentes en ese árbol.
    """

    def filter_tree(t: GithubTree) -> Set[str]:
        return {
            e.path
            for e in t.tree
            if e.type == "blob" and (not match_re or match_re.match(e.path))
        }

    cur_files = filter_tree(cur_tree)
    preserve_files = filter_tree(preserve_from) if preserve_from else set()

    deletions = cur_files - new_files - preserve_files
    return [InputGitTreeElement(path, "100644", "blob", sha=None) for path in deletions]
