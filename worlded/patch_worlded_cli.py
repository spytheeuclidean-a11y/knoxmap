"""Add a --generate-map=<project.pzw> switch to PZWorldEd.

WorldEd can convert a BMP project to TMX and compile the lots, but only from its
File menu; every command-line switch it ships is a developer self-test. That one
gap is the only manual step in the KnoxMap pipeline.

The two menu items do very little of their own:

    File > BMP To TMX > All Cells...
        BMPToTMX::instance()->generateWorld(worldDoc, BMPToTMX::GenerateAll)

    File > Generate Lots 8x8 > All Cells...
        LotFilesManager256::instance()->generateWorld(
            worldDoc, LotFilesManager256::GenerateAll)

Their dialogs only collect settings that already live in the .pzw, which
knoxbuild pre-fills. So this adds a switch that opens a project and calls both
in order, reusing main.cpp's existing headless pattern (the one behind
--validate-bmp-generation) and the includes it already has.

    python patch_worlded_cli.py <path to PZ_Mapping_Tools source>
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

DECL_ANCHOR = "    QString validateBmpGenerationProject;"
DECL_ADD = """    QString validateBmpGenerationProject;
    QString generateMapProject;
    QRect generateMapCells;"""

ARG_ANCHOR = """        const QString bmpValidationPrefix =
                QLatin1String("--validate-bmp-generation=");"""
ARG_ADD = """        const QString generateCellsPrefix =
                QLatin1String("--cells=");
        if (argument.startsWith(generateCellsPrefix)) {
            const QStringList parts =
                    argument.mid(generateCellsPrefix.size()).split(QLatin1Char(','));
            if (parts.size() == 4) {
                generateMapCells = QRect(
                        QPoint(parts.at(0).toInt(), parts.at(1).toInt()),
                        QPoint(parts.at(2).toInt(), parts.at(3).toInt()));
            }
            continue;
        }
        const QString generateMapPrefix =
                QLatin1String("--generate-map=");
        if (argument.startsWith(generateMapPrefix)) {
            generateMapProject = argument.mid(generateMapPrefix.size());
            continue;
        }
        const QString bmpValidationPrefix =
                QLatin1String("--validate-bmp-generation=");"""

GATE_ANCHOR = "            || !validateBmpGenerationProject.isEmpty()"
GATE_ADD = """            || !validateBmpGenerationProject.isEmpty()
            || !generateMapProject.isEmpty()"""

HANDLER_ANCHOR = "    if (!validateBmpGenerationProject.isEmpty()) {"
HANDLER_ADD = '''    if (!generateMapProject.isEmpty()) {
        if (!w.openFile(generateMapProject)) {
            qCritical().noquote() << "Could not open project:"
                                  << generateMapProject;
            return 60;
        }
        Document *document = DocumentManager::instance()->currentDocument();
        WorldDocument *worldDocument =
                document ? document->asWorldDocument() : nullptr;
        if (!worldDocument) {
            qCritical().noquote() << "Not a world project:"
                                  << generateMapProject;
            return 61;
        }

        // Both steps end by showing a modal "Finished!" message box, and Generate
        // Lots may add a failure list in another. Headless there is nobody to
        // click them: BMP to TMX's box blocked a fresh install's compile
        // forever, and Generate Lots' held each batch until someone found it
        // on their desktop. Close any modal the moment it opens - the log
        // lines already say everything the boxes do. Started before either
        // step, since a message box runs its own event loop and only a timer
        // that already exists can fire inside it.
        QTimer dialogCloser;
        QObject::connect(&dialogCloser, &QTimer::timeout, [] {
            if (QWidget *modal = QApplication::activeModalWidget()) {
                qInfo().noquote() << "Dismissed dialog:" << modal->windowTitle();
                modal->close();
            }
        });
        dialogCloser.start(100);

        // Skip conversion when every cell already points at a TMX. Besides
        // saving many minutes on a re-run, it avoids re-entering a step that
        // has been seen to die at the end of a large map, after writing all of
        // its output but before the assignments could be saved.
        int cellsWithMaps = 0;
        int cellsTotal = 0;
        for (int cy = 0; cy < worldDocument->world()->height(); cy++) {
            for (int cx = 0; cx < worldDocument->world()->width(); cx++) {
                WorldCell *cell = worldDocument->world()->cellAt(cx, cy);
                if (cell == nullptr)
                    continue;
                cellsTotal++;
                if (!cell->mapFilePath().isEmpty())
                    cellsWithMaps++;
            }
        }

        if (cellsTotal > 0 && cellsWithMaps == cellsTotal) {
            qInfo().noquote() << "BMP to TMX: skipped," << cellsWithMaps
                              << "cells already have maps";
        } else {
            qInfo().noquote() << "BMP to TMX: all cells";
            if (!BMPToTMX::instance()->generateWorld(
                        worldDocument, BMPToTMX::GenerateAll)) {
                qCritical().noquote() << "BMP to TMX failed:"
                                      << BMPToTMX::instance()->errorString();
                return 62;
            }
        }

        // Compiling a whole town in one process exhausts memory - every cell
        // adds to the map cache and nothing is released, so a 572-cell map
        // climbed to 13.7 GB and brought the machine to its knees before
        // finishing a sixth of the job. --cells lets a driver hand the work
        // over in batches, one fresh process each, which keeps the peak flat.
        const QString lotsDir =
                worldDocument->world()->getGenerateLotsSettings().exportDir;
        const QRect batchRect = generateMapCells.isValid()
                ? CombinedCellMaps::outputCellRect(
                        worldDocument->world()->gridFormat(),
                        generateMapCells.translated(
                            worldDocument->world()->getGenerateLotsSettings().worldOrigin))
                : QRect();
        int alreadyWritten = QDir(lotsDir).entryList(
                QStringList() << QLatin1String("*.lotheader"), QDir::Files).size();
        int pendingInBatch = 0;
        if (batchRect.isValid()) {
            QDir exportDir(lotsDir);
            for (int cy = batchRect.top(); cy <= batchRect.bottom(); cy++) {
                for (int cx = batchRect.left(); cx <= batchRect.right(); cx++) {
                    if (!exportDir.exists(QString::fromLatin1("%1_%2.lotheader")
                                          .arg(cx).arg(cy)))
                        pendingInBatch++;
                }
            }
            // Every cell of this batch is on disk from an earlier run. Doing it
            // again would cost the same minutes for byte-identical output, so a
            // re-run picks up where it stopped instead of starting over.
            if (pendingInBatch == 0) {
                qInfo().noquote() << "Generate Lots: batch" << generateMapCells
                                  << "already written, skipping";
                return 0;
            }
        }

        LotFilesManager256::GenerateMode mode = LotFilesManager256::GenerateAll;
        if (generateMapCells.isValid()) {
            QList<WorldCell *> selection;
            for (int cy = generateMapCells.top(); cy <= generateMapCells.bottom(); cy++) {
                for (int cx = generateMapCells.left(); cx <= generateMapCells.right(); cx++) {
                    if (cx < 0 || cy < 0 ||
                            cx >= worldDocument->world()->width() ||
                            cy >= worldDocument->world()->height())
                        continue;
                    if (WorldCell *cell = worldDocument->world()->cellAt(cx, cy))
                        selection += cell;
                }
            }
            if (selection.isEmpty()) {
                qCritical().noquote() << "No cells in" << generateMapCells;
                return 66;
            }
            worldDocument->setSelectedCells(selection);
            mode = LotFilesManager256::GenerateSelected;
            qInfo().noquote() << "Generate Lots 8x8: cells"
                              << generateMapCells << "(" << selection.size() << ")";
        } else {
            qInfo().noquote() << "Generate Lots 8x8: all cells";
        }

        LotFilesManager256 *lotManager = LotFilesManager256::instance();

        lotManager->setHoleFillMode(LotFilesManager256::ReportHoles);
        if (!lotManager->generateWorld(worldDocument, mode)) {
            qCritical().noquote() << "Generate Lots failed:"
                                  << lotManager->errorString();
            return 63;
        }

        // generateWorld only starts worker threads - the block that waited for
        // them is #if 0'd out, and the GUI simply keeps running while they
        // finish. Headless we must hold the event loop open ourselves, or the
        // process exits and the workers die mid-write.
        //
        // The expected count below is reported for information; it is not what
        // decides the export is finished - see the loop.
        const QRect outputRect = CombinedCellMaps::outputCellRect(
                worldDocument->world()->gridFormat(),
                QRect(worldDocument->world()->getGenerateLotsSettings().worldOrigin,
                      worldDocument->world()->size()));
        int expectedCells = qMax(1, outputRect.width() * outputRect.height());
        if (batchRect.isValid()) {
            // Only this batch's share, on top of what earlier batches wrote.
            //
            // Counted cell by cell rather than by area: batches share their
            // edges, because a 256-tile output cell straddling two 300-tile
            // source cells belongs to both. Those shared cells are rewritten
            // and the file count does not move, so an area-based guess waits
            // for a cell that will never appear and every batch pays the stall
            // timeout.
            expectedCells = qMin(expectedCells, alreadyWritten + pendingInBatch);
        }
        qInfo().noquote() << "Expecting" << expectedCells << "output cells";

        QElapsedTimer overall;
        overall.start();
        QElapsedTimer quiet;
        quiet.start();
        QElapsedTimer poll;
        poll.start();
        qint64 lastBytes = -1;
        bool finished = false;
        const qint64 timeoutMs = 6LL * 60 * 60 * 1000;   // 6 hours
        const qint64 stallMs = 10LL * 60 * 1000;         // 10 minutes
        while (overall.elapsed() < timeoutMs) {
            // Keep pumping and never sleep: generation is driven by a 30Hz
            // QTimer in LotFilesManager256, and starving it makes the manager
            // see an idle moment between jobs and stop early - that truncated
            // a 572-cell town to 73 cells with no error.
            qApp->processEvents(QEventLoop::AllEvents, 20);

            // Finished means the manager says so. It stops its work timer only
            // once every queued cell is generated, every worker has written its
            // output and its threads are stopped. Anything read off the export
            // folder is a guess: WorldEd writes a cell's .lotheader before the
            // cell's contents, so "every header exists and the folder has been
            // quiet for two seconds" came true while the cell holding a real
            // town's textile factory was still being written, and the process
            // exited with that cell cut short.
            if (!lotManager->isGenerating()) {
                finished = true;
                break;
            }
            if (poll.elapsed() < 2000)
                continue;
            poll.restart();

            // Stall detection only: no new output for ten minutes.
            QDir dir(lotsDir);
            const QStringList produced =
                    dir.entryList(QStringList() << QLatin1String("*.lotheader")
                                                << QLatin1String("*.lotpack")
                                                << QLatin1String("chunkdata*"),
                                  QDir::Files);
            qint64 bytes = 0;
            for (const QString &name : produced)
                bytes += QFileInfo(dir.filePath(name)).size();
            if (bytes != lastBytes) {
                lastBytes = bytes;
                quiet.restart();
            } else if (quiet.elapsed() > stallMs) {
                qCritical().noquote()
                        << "Generate Lots stalled with no new output for"
                        << stallMs / 60000 << "minutes";
                break;
            }
        }

        const int written = QDir(lotsDir).entryList(
                    QStringList() << QLatin1String("*.lotheader"),
                    QDir::Files).size();
        if (written <= 0) {
            qCritical().noquote()
                    << "Generate Lots produced no files in" << lotsDir;
            return 64;
        }
        if (!finished) {
            qCritical().noquote()
                    << "Generate Lots incomplete:" << written << "of"
                    << expectedCells << "cells in" << lotsDir;
            return 65;
        }
        qInfo().noquote() << "Generate Lots wrote" << written << "of"
                          << expectedCells << "cells to" << lotsDir;

        qInfo().noquote() << "Map generated:" << generateMapProject;
        return 0;
    }

    if (!validateBmpGenerationProject.isEmpty()) {'''

STEPS = [
    ("declaration", DECL_ANCHOR, DECL_ADD),
    ("argument parsing", ARG_ANCHOR, ARG_ADD),
    ("headless gate", GATE_ANCHOR, GATE_ADD),
    ("handler", HANDLER_ANCHOR, HANDLER_ADD),
]


HEADER_ANCHOR = "    QString errorString() const { return mError; }"
HEADER_ADD = """    QString errorString() const { return mError; }
    // True from generateWorld until the last cell is written and the worker
    // threads are stopped - the manager's own notion of finished.
    bool isGenerating() const { return mTimer.isActive(); }"""


# GPL-2.0 section 2(a): modified files must carry a prominent notice that
# they were changed, and when. Appended at the end so no line of the original
# code moves.
MODIFIED_NOTICE = """
/*
 * Modified by KnoxMap (https://github.com/spytheeuclidean-a11y/knoxmap),
 * 2026-09: {what}
 * These modifications are distributed under the same GNU General Public
 * License as the rest of this file.
 */
"""


def _mark_modified(path: Path, what: str) -> None:
    text = path.read_text(encoding="utf-8")
    if "Modified by KnoxMap" not in text:
        path.write_text(text.rstrip("\n") + "\n" + MODIFIED_NOTICE.format(what=what),
                        encoding="utf-8")


def patch_header(root: Path) -> bool:
    header = root / "WorldEd" / "src" / "editor" / "lotfilesmanager256.h"
    text = header.read_text(encoding="utf-8")
    if "bool isGenerating()" in text:
        return True
    backup = header.with_suffix(".h.orig")
    if not backup.exists():
        shutil.copy2(header, backup)
    if text.count(HEADER_ANCHOR) != 1:
        print("header anchor not found exactly once - aborting", file=sys.stderr)
        return False
    header.write_text(text.replace(HEADER_ANCHOR, HEADER_ADD, 1), encoding="utf-8")
    _mark_modified(header, "added LotFilesManager256::isGenerating() for headless compiling.")
    print("patched: lotfilesmanager256.h")
    return True


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".")
    if not patch_header(root):
        return 3
    main_cpp = root / "WorldEd" / "src" / "editor" / "main.cpp"
    if not main_cpp.is_file():
        print(f"main.cpp not found under {root}", file=sys.stderr)
        return 2

    text = main_cpp.read_text(encoding="utf-8")
    if "--generate-map=" in text:
        print("already patched")
        return 0

    backup = main_cpp.with_suffix(".cpp.orig")
    if not backup.exists():
        shutil.copy2(main_cpp, backup)
        print(f"backed up to {backup.name}")

    for label, anchor, replacement in STEPS:
        if text.count(anchor) != 1:
            print(f"anchor for {label} appears {text.count(anchor)} times, "
                  f"expected once — aborting without writing", file=sys.stderr)
            return 3
        text = text.replace(anchor, replacement, 1)
        print(f"patched: {label}")

    main_cpp.write_text(text, encoding="utf-8")
    _mark_modified(main_cpp, "added the --generate-map and --cells command-line "
                             "switches for headless map compiling.")
    print(f"wrote {main_cpp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
