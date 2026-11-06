# Stew Decal Enhancer

<p align="center">
  <img width="256" height="256" alt="lidico" src="https://github.com/user-attachments/assets/e5fe0fc7-1bcb-4d1e-8270-3ebf20b4adc4" />
</p>
<img width="1001" height="938" alt="program preview" src="https://github.com/user-attachments/assets/413b66ca-74c5-4a04-b1fa-e7b3e921c872" />
<img width="1840" height="992" alt="image" src="https://github.com/user-attachments/assets/9c8458ba-f8dc-4865-bd88-e5267da8ea34" />


Choose how many of each premium skill decal the Mushroom Lady's stew may still
give you in the LET IT DIE offline edition (PC). Decals you already have enough
of stop coming out of the stew. Lost Bag and Collab decals can be added to it.

## Before you start: SHA

```
The game checks BrgGame-Steam.exe against a SHA list inside it. While that
check is on (SHA locked), the game will not start if any byte of the exe was
changed. masters.db and the save can be changed either way.
This program does NOT unlock SHA; it only reads the list to see whether it
is switched off.

While SHA is locked, Bake Stew and Patch game are greyed out and the
message says:
    First you have to unlock SHA (this program doesn't has that feature)

Settings > Get SHA unlocker in Github opens
    https://github.com/Grimfuldev/let_it_die_borderless/releases/tag/v0.4
(its Reticle UI has the unlock button). After unlocking, press Check again
in Settings, Refresh, or just come back to this window.
```

## How it works

```
0. Unlock SHA with the tool above.
1. Start the program. Settings > Browse to steam.exe (or BrgGame-Steam.exe).
   The game folder, masters.db and brggame.sav are found from there.
2. Close the game. Settings > Patch game.
3. Set a max on each decal with - / + or by typing.
4. Click Bake Stew.
5. Play. Every stew pull updates the save; the program sees it and bakes
   the stew again, and the very next pull already follows it.
```

## Check Lineup in the game

```
Pulls always use the stew as it is in masters.db right now, even while the
game is running. Only the Mushroom Lady's Check Lineup screen is built when
you open her shop, so after a bake it keeps showing the old lineup until
you leave and re-enter her shop. The program reminds you
of this each time it changes the stew.
```

## Patch game (Settings)

```
Greyed out while the game is running or while SHA is locked.
Checks every byte before writing. If the exe or save is not what it expects,
nothing is changed.

- masters.db: adds the Lost Bag and Collab decals to the stew table
  (master_skillgacha_odds), at odds 0 until the bake right after sets them.
  Decals already there are left as they are. The decals it adds are listed
  in a small extra table in masters.db (stew_decal_enhancer_added; the game
  never reads it), so they can be told apart from decals anyone else added.
- BrgGame-Steam.exe: the decal list is rolled 1 at a time instead of 1000,
  each roll uses fresh randomness, and masters.db is no longer opened as
  "immutable" (never changes): SQLite checks the file for changes before
  each read, so every pull uses the stew as it is right now.
  Parts already patched are skipped.
- brggame.sav: empties the saved pre-rolled decal list (gacha > normal > sklids).
  Nothing else in the save changes. Left alone if the list is already empty.

No backup files are made. Back up your own save if you want one.
```

## Revert patch (Settings)

```
Shown instead of Patch game once the exe is patched (or, while SHA is locked,
when the stew table still has decals this program added).
Works without backup files:
- masters.db: the same as Restore Decals (below).
- BrgGame-Steam.exe: only the bytes this program changed are written back,
  so the exe is again your SHA-unlocked exe as it was before Patch game.
  The SHA unlocker's own changes are never touched.
The save is not touched.

If SHA is locked again (the SHA unlocker restored the Steam exe), this
program's exe changes are already gone, so Revert patch only restores the
stew table in masters.db and leaves the exe alone.
```

## Restore Decals (Settings)

```
masters.db only; the exe and the save are not touched. Works while the game
runs. Greyed out when this program has no decals in the stew.
- removes the decals this program added to the stew table
- puts the original odds back on the game's own stew decals
  (master_skillgacha_odds.json next to the program)
- decals added by anyone else (e.g. PlayStation decals you added yourself)
  are left exactly as they are. Bake Stew never changes their odds either.
The game stays patched: Bake Stew keeps working and puts this program's
decals back into the stew (so does the automatic bake after a pull).
```

## Decals

```
-  / +          change the max. Inf (no limit) counts as -1:
                  + on Inf -> 0,  - on 0 -> Inf,  - on Inf does nothing.
                  Up to 99 (the game's cap).
RMB on -        max 0 (never from the stew)
RMB on +        Inf
Type in box     a number, or empty / inf for no limit. Clicking anywhere
                else ends typing and keeps the value.
Double-click    (two LMB within 0.5 s) on the image: put the decal name in Browse
RMB on image    details: id, source, owned (inventory + equipped), odds
Badge           owned / max. Red when the max is reached.
```

The program never adds or removes decals from your inventory. If you own
more than the max, you keep them all; the decal is only set to 0 in the
stew until you own fewer or raise the max above what you have.

Owned = inventory count (`psskl` cnt) + decals equipped on your fighters
(`eqskl` "1"). Negative `eqskl` entries are ignored.

## Bake Stew

```
Greyed out until the game is patched (Settings > Patch game) and SHA is unlocked.
If this program's decals are not in the stew table (after Restore Decals),
the bake adds them back first.
For every decal: odds 0 if its max is 0, if you own its max, or if its group
(Collab / Lost Bag) is unticked. Otherwise its normal stew odds.
A decal missing from the stew table (for example one added to
premium_decals.json later) gets its row first.
Bake Stew * means your settings differ from what is in masters.db.

All set to 0     If your settings leave no decal at Inf or above 0, nothing is
                 written: "At least one decal must be inf or greater than 0".
All maxed        If every decal you allow is already at its max, the stew can't
                 be empty (the game would hang), so: "All decals maxed, all
                 maxed decals are set to obtainable". Every decal you allow
                 (max above 0, group ticked) goes back in at its normal
                 stew odds and the game picks among them as usual. As soon as
                 any decal is below its max again (sold, or max raised), the
                 stew follows your settings again.
```

## Top bar

```
Collab, Lost Bag   unticked = that group bakes as 0 and its art turns grey.
                   Your max values are kept.
Sort               Max val, Min val, Stars(+), Stars(-), Owned
                   (Max val / Min val: decals with a max set come first, Inf last)
                   (Owned: most owned first, inventory + equipped; updates
                   after each stew pull)
Browse             RMB on the ✕ next to it lists these keywords.
                   filter by name or decal id. "4 star" / "4 stars" shows only
                   4-star decals (a number on its own searches names and ids).
                   "owned" shows only the premium decals you have now
                   (inventory or equipped); it updates after each stew pull.
                   "pull" (or "stew") shows only the decals the stew can give now
                   (odds above 0 in masters.db); it updates after each bake.
- [n] + / Set Browsed
                   next to Browse: pick a max with the same rules as a decal
                   (-, +, RMB, typing), then Set Browsed gives that max to every
                   decal currently shown. Empty Browse = all decals.
```

## Bottom bar

```
Messages     what the program did. RMB on it clears the messages.
Shortcut     click, then press a key: that key hides/shows the window.
             RMB removes it.
Refresh      re-read the save, masters.db and the decal art, apply Browse and
             Sort again, and report how many decals the stew can give right now
Settings     paths, SHA state, Get SHA unlocker in Github, Check again,
             Show stars, Patch game / Revert patch, Restore Decals
```

## Files

```
premium_decals.json            decal list (ids, names, stars, groups, stew odds)
master_skillgacha_odds.json    original stew table, used by Revert patch
settings.ini                   paths, shortcut, sort, groups, show stars
decal_max.json                 your max per decal (missing = Inf)
stew.lock                      while running; starting again closes the old one
UI_Assets                      UI background.webp, let it die cursor.webp, lidico.ico
```

## Decal art

```
The decal images are read from your own game install
(BrgGame\CookedPCConsole\UI_<decal>_S_SF.upk) while the program runs and are
kept in memory only. The program never saves, exports or ships them.
PlayStation-only decals are not included: the PC game has no art for them.
```

## License and disclaimer

```
This is an unofficial fan tool. It is not affiliated with, authorized, or
endorsed by Grasshopper Manufacture or GungHo Online Entertainment.
LET IT DIE, its characters, names, artwork and setting remain their property.
Back up your save before patching. Use at your own risk.
```

Thanks to oberlinx for the decal viewer site, which made building the decal list a lot easier: https://oberlinx.github.io/let-it-die-model-viewer/decals.html
