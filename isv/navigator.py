"""Sequenza di immagini e cartelle usata da visualizzatore e slideshow."""
import random

from .archive import parent_of
from .utils import (browse_boundary, collect_image_folders, find_folder_with_images,
                    has_images, list_images, list_subdirs, samepath)


class Navigator:
    """
    Tiene la posizione corrente (cartella + immagine).

    - include_sub=True: la sequenza comprende tutte le sottocartelle di `folder`;
      a fine cartella si passa alla successiva, e il salto cartella resta dentro
      l'albero di partenza.
    - include_sub=False: si scorre solo la cartella corrente; il salto cartella
      va alla cartella successiva/precedente sul disco (come ACDSee).
    - shuffle_folders=True ("cartelle casuali"): le cartelle si percorrono in ordine
      casuale, ma le immagini di ogni cartella restano ordinate. Con una sola cartella
      si pescano anche le cartelle vicine (quelle della cartella che la contiene).
    """

    def __init__(self, folder, *, images=None, start=None, include_sub=False,
                 shuffle=False, loop=False, sort="name", reverse=False, folders=None,
                 start_folder=None, shuffle_folders=False):
        """folders: elenco esplicito di cartelle da percorrere (cartelle selezionate)."""
        self.root = folder
        self.explicit_start = start is not None    # aperto su un'immagine precisa (niente "riprendi")
        self.include_sub = (include_sub or folders is not None) and images is None
        self.shuffle = shuffle and not shuffle_folders
        self.shuffle_folders = False
        self.walk_folders = False      # a fine cartella passa alla successiva (dopo le cartelle casuali)
        self._ordered = None           # (cartelle in ordine, expandable) prima delle cartelle casuali
        self.loop = loop
        self.sort = sort
        self.reverse = reverse
        self.custom = images is not None
        self.folder_changed = False
        self.boundary = browse_boundary(folder)

        if folders is not None and images is None:
            self.folders = list(folders)
            if shuffle and len(self.folders) > 1:
                random.shuffle(self.folders)
        elif self.include_sub:
            self.folders = collect_image_folders(folder)
            if shuffle and len(self.folders) > 1:
                random.shuffle(self.folders)
        else:
            self.folders = [folder]
        # Elenco "aperto": si può proseguire con le cartelle vicine sul disco.
        # Chiuso quando è un insieme scelto (selezione o albero con più cartelle).
        self.expandable = folders is None and len(self.folders) <= 1
        self.fi = 0
        if start_folder:
            from .utils import is_inside
            for i, f in enumerate(self.folders):
                if is_inside(f, start_folder):
                    self.fi = i
                    break
        if start and self.include_sub:
            sdir = parent_of(start)
            for i, f in enumerate(self.folders):
                if samepath(f, sdir):
                    self.fi = i
                    break

        if self.custom:
            self.images = list(images)
            if shuffle:
                random.shuffle(self.images)
        else:
            self.images = self._load(self.folders[self.fi]) if self.folders else []
        self.ii = 0
        if start and not self.shuffle:
            for i, p in enumerate(self.images):
                if samepath(p, start):
                    self.ii = i
                    break
        if shuffle_folders and not self.custom:
            # Si parte dalla cartella scelta (o da quella con l'immagine di partenza);
            # con più cartelle e nessun punto di partenza anche la prima è a caso.
            # Con un elenco di immagini (ricerca, filtro, selezione) resta tutto com'è:
            # PagGiù / PagSu passano comunque alle cartelle casuali.
            self.enable_random_folders(
                keep_current=bool(start or start_folder) or len(self.folders) <= 1)

    # ------------------------------------------------------------------ info
    def _load(self, folder):
        imgs = list_images(folder, self.sort, self.reverse)
        if self.shuffle:
            random.shuffle(imgs)
        return imgs

    @property
    def folder(self):
        if self.custom and self.images:
            return parent_of(self.images[self.ii])
        return self.folders[self.fi] if self.folders else self.root

    def current(self):
        if 0 <= self.ii < len(self.images):
            return self.images[self.ii]
        return None

    def peek(self, d=1):
        n = self.ii + d
        if 0 <= n < len(self.images):
            return self.images[n]
        return None

    def position(self):
        return self.ii + 1, len(self.images)

    def folder_position(self):
        if len(self.folders) > 1:
            return self.fi + 1, len(self.folders)
        return None

    # ------------------------------------------------------------ movimento
    def step(self, d):
        """Immagine successiva (d=+1) o precedente (d=-1). False se non si muove."""
        self.folder_changed = False
        if not self.images:
            return self.jump_folder(d)
        n = self.ii + d
        if 0 <= n < len(self.images):
            self.ii = n
            return True
        if self.include_sub or self.shuffle_folders or self.walk_folders:
            return self._move_folder(d, land_end=d < 0)
        if self.loop and len(self.images) > 1:
            self.ii = n % len(self.images)
            return True
        return False

    def jump_folder(self, d):
        """Salta alla prima immagine della cartella successiva/precedente.
        Il salto con ↓/↑ gira sempre in tondo: dalla prima cartella si passa all'ultima
        e viceversa (anche senza "Ripeti", che vale per lo scorrimento automatico)."""
        self.folder_changed = False
        return self._move_folder(d, land_end=False, wrap=True)

    # ------------------------------------------------------ cartelle casuali
    def _folder_pool(self, cur):
        """Cartelle con immagini tra cui pescare a caso."""
        if len(self.folders) > 1:
            return list(self.folders)
        # una sola cartella: anche le sorelle (e le loro sottocartelle), senza però
        # risalire oltre il limite del salto cartella (es. D:\Foto o la cartella Immagini)
        from .utils import is_inside
        root = cur
        parent = parent_of(cur)
        if parent and not samepath(parent, cur) and self.boundary \
                and is_inside(parent, self.boundary):
            root = parent
        pool = collect_image_folders(root)
        return pool or [cur]

    def enable_random_folders(self, keep_current=True):
        """Passa alle cartelle in ordine casuale (immagini ordinate dentro ogni cartella).
        keep_current: la cartella mostrata resta la prima dell'elenco, così ↑ / PagSu
        tornano indietro lungo le cartelle già viste."""
        if self.shuffle_folders:
            return
        cur_img = self.current()
        cur = self.folder
        pool = self._folder_pool(cur)
        if not any(samepath(f, cur) for f in pool):
            pool = [cur] + pool
        self._ordered = (list(pool), self.expandable)
        others = [f for f in pool if not samepath(f, cur)]
        random.shuffle(others)
        was_shuffled = self.shuffle
        self.shuffle_folders = True
        self.shuffle = False
        self.expandable = False
        if keep_current or not others:
            self.folders = [cur] + others
            self.fi = 0
            if self.custom:
                self.custom = False
                self.images = self._load(cur)
            elif was_shuffled:
                self.images = self._load(cur)    # di nuovo in ordine
            else:
                return
            self.ii = 0
            for i, p in enumerate(self.images):
                if cur_img and samepath(p, cur_img):
                    self.ii = i
                    break
            return
        # si parte da una cartella a caso
        self.folders = others + [cur]
        random.shuffle(self.folders)
        self.custom = False
        for fi, f in enumerate(self.folders):
            imgs = self._load(f)
            if imgs:
                self.fi, self.images, self.ii = fi, imgs, 0
                return

    def disable_random_folders(self):
        """Torna alle cartelle in ordine, ripartendo da quella mostrata: ↓ / PagGiù e la
        fine della cartella proseguono con la cartella che la segue nell'ordine normale."""
        if not self.shuffle_folders:
            return
        self.shuffle_folders = False
        cur = self.folder
        if self._ordered:
            folders, self.expandable = self._ordered
        else:
            folders = list(self.folders)
        self._ordered = None
        fi = next((i for i, f in enumerate(folders) if samepath(f, cur)), None)
        if fi is None:
            folders.insert(0, cur)
            fi = 0
        self.folders, self.fi = folders, fi
        # lo slideshow stava già girando tra le cartelle: continua a farlo, in ordine
        self.walk_folders = len(folders) > 1

    def first(self):
        if self.images:
            self.ii = 0

    def last(self):
        if self.images:
            self.ii = len(self.images) - 1

    def _move_folder(self, d, land_end, wrap=False):
        """
        Passa alla cartella successiva/precedente dell'elenco, partendo SEMPRE dalla
        cartella attualmente mostrata. Oltre la fine dell'elenco:
        - con "Ripeti" e più cartelle in elenco si ricomincia dall'altro capo;
        - altrimenti si prosegue con la cartella vicina sul disco, che viene
          aggiunta all'elenco (così ↑ riporta indietro correttamente).
        """
        if self.custom:
            # Slideshow di immagini selezionate: da qui in poi si va per cartelle.
            self.folders, self.fi, self.custom = [self.folder], 0, False
            self.expandable = True
        loop = self.loop or wrap
        nf = len(self.folders)
        fi = self.fi
        for _ in range(max(nf, 1)):
            fi += d
            if 0 <= fi < len(self.folders):
                imgs = self._load(self.folders[fi])
                if imgs:
                    return self._enter(fi, imgs, land_end)
                continue
            # oltre l'estremità dell'elenco
            if self.expandable:
                if self._extend(d, land_end):
                    return True
                if not loop:
                    return False
                # in fondo (o in cima) all'albero: si riparte dall'altro capo
                return self._wrap(d, land_end)
            if loop and len(self.folders) > 1:
                fi %= len(self.folders)
                imgs = self._load(self.folders[fi])
                if imgs:
                    return self._enter(fi, imgs, land_end)
                continue
            return False
        return False

    def _wrap(self, d, land_end):
        """Elenco "aperto" arrivato al limite (es. D:\\Foto): va all'ultima cartella con
        immagini dell'albero andando indietro, alla prima andando avanti."""
        b = self.boundary
        if not b:
            return False
        if d > 0:
            target = b if has_images(b) else find_folder_with_images(b, True, b)
        else:
            node = b
            while True:
                subs = list_subdirs(node)
                if not subs:
                    break
                node = subs[-1]
            if samepath(node, b):
                target = b if has_images(b) else None
            else:
                target = node if has_images(node) else find_folder_with_images(node, False, b)
        if not target or samepath(target, self.folders[self.fi]):
            return False
        imgs = self._load(target)
        if not imgs:
            return False
        # si ricomincia un elenco nuovo dall'altro capo: da lì ↑/↓ proseguono normalmente
        self.folders = [target]
        return self._enter(0, imgs, land_end)

    def _extend(self, d, land_end):
        if self.shuffle and len(self.folders) > 1:
            return False  # in ordine casuale non ha senso "la cartella vicina"
        edge = self.folders[-1] if d > 0 else self.folders[0]
        target = find_folder_with_images(edge, forward=d > 0, boundary=self.boundary)
        if not target or any(samepath(target, f) for f in self.folders):
            return False
        imgs = self._load(target)
        if not imgs:
            return False
        if d > 0:
            self.folders.append(target)
            fi = len(self.folders) - 1
        else:
            self.folders.insert(0, target)
            fi = 0
        return self._enter(fi, imgs, land_end)

    def _enter(self, fi, imgs, land_end):
        self.fi = fi
        self.images = imgs
        self.ii = len(imgs) - 1 if land_end else 0
        self.folder_changed = True
        return True

    def remove_current(self):
        """Toglie l'immagine corrente (es. dopo eliminazione)."""
        if not self.images:
            return
        del self.images[self.ii]
        if self.ii >= len(self.images):
            self.ii = max(0, len(self.images) - 1)
