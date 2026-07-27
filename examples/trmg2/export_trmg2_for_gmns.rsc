/*
    export_trmg2_for_gmns.rsc
    ------------------------------------------------------------------------
    One-click GISDK export of the few TRMG2 items that live only in TransCAD's
    internal formats, for an open-source GMNS / Python assignment pipeline.

    Exports:
      1. roadway line layer + node layer  -> shapefile, WITH from_node_id / to_node_id
      2. assignment OD matrices           -> OMX (preferred) + CSV per core
      3. transit skims                    -> OMX + CSV
      4. (optional) PA / logsum / roadway-skim matrices
      5. reports turn_prohibitions.bin row count (empty vs populated)

    Usage (TransCAD): Tools > GIS Developer's Kit > compile this file, then run
    the macro "Export TRMG2 for GMNS". EDIT the paths in the CONFIG block first.

    Notes
      - Written against TransCAD 9 GISDK. OMX export uses CopyMatrix with an .omx
        filename (TC 9.0+); if your build lacks OMX, the CSV-per-core files are a
        complete fallback. CSV export (ExportMatrix ... "CSV") works on all versions.
      - GetEndpoints(id) returns the two end-node IDs in the link's digitized
        (from -> to) order, i.e. GMNS A -> B. (If your build spells it GetEndPoints,
        change the one call below.)
      - No behavioral data is touched; this only re-serializes geometry + matrices.
*/

Macro "Export TRMG2 for GMNS"

    // =========================== CONFIG (EDIT) ===========================
    // Point these at the master network OR a built base-2020 scenario.
    hwy_dbd   = "C:\\TRMG2\\master\\networks\\master_links.dbd"          // roadway line geodatabase
    assn_dir  = "C:\\TRMG2\\scenarios\\base_2020\\output\\assignment\\roadway"  // od_veh_trips_*.mtx
    tskim_dir = "C:\\TRMG2\\scenarios\\base_2020\\output\\skims\\transit"       // transit skims
    rskim_dir = "C:\\TRMG2\\scenarios\\base_2020\\output\\skims\\roadway"       // sov/hov roadway skims (optional)
    input_net = "C:\\TRMG2\\scenarios\\base_2020\\input\\networks"              // turn_prohibitions.bin
    out_dir   = "C:\\TRMG2_export"                                              // everything is written here
    periods   = {"AM", "MD", "PM", "NT"}
    // =====================================================================

    if GetDirectoryInfo(out_dir, "Directory") = null then CreateDirectory(out_dir)
    log = out_dir + "\\export_log.txt"
    fptr = OpenFile(log, "w")
    WriteLine(fptr, "TRMG2 -> GMNS export log")

    // ---------- 1. ROADWAY GEOMETRY (line + node), with from/to node id ----------
    if GetFileInfo(hwy_dbd) <> null then do
        {nlyr, llyr} = GetDBLayers(hwy_dbd)          // [1] node layer, [2] line layer
        map = CreateMap("trmg2", {{"Scope", GetDBInfo(hwy_dbd)[1]}})
        llyr = AddLayer(map, llyr, hwy_dbd, llyr)
        nlyr = AddLayer(map, nlyr, hwy_dbd, nlyr)

        // add from_node_id / to_node_id to the link layer if absent
        SetLayer(llyr)
        existing = GetFields(llyr, "All")
        have = ArrayPosition(existing[1], {"from_node_id"}, )
        if have = 0 then do
            strct = GetTableStructure(llyr)
            for i = 1 to strct.length do strct[i] = strct[i] + {strct[i][1]} end
            strct = strct + {{"from_node_id", "Integer", 12, 0, "False", , , , , , , "from_node_id"}}
            strct = strct + {{"to_node_id",   "Integer", 12, 0, "False", , , , , , , "to_node_id"}}
            ModifyTable(llyr, strct)
        end

        // fill endpoints (digitized from -> to = GMNS A -> B)
        SetLayer(llyr)
        rh = GetFirstRecord(llyr + "|", null)
        nfill = 0
        while rh <> null do
            ep = GetEndpoints(llyr.ID)               // {from_node_id, to_node_id}
            llyr.from_node_id = ep[1]
            llyr.to_node_id   = ep[2]
            nfill = nfill + 1
            rh = GetNextRecord(llyr + "|", null, null)
        end
        WriteLine(fptr, "links with endpoints filled: " + String(nfill))

        // export to shapefile (link .dbf now carries from_node_id / to_node_id)
        ExportGeography(llyr, out_dir + "\\trmg2_link.shp", {{"Layer Name", "trmg2_link"}})
        ExportGeography(nlyr, out_dir + "\\trmg2_node.shp", {{"Layer Name", "trmg2_node"}})
        WriteLine(fptr, "wrote trmg2_link.shp + trmg2_node.shp")
        CloseMap(map)
    end
    else WriteLine(fptr, "SKIP geometry: hwy_dbd not found -> " + hwy_dbd)

    // ---------- 2. ASSIGNMENT OD MATRICES (6 vehicle classes per period) ----------
    for i = 1 to periods.length do
        p = periods[i]
        f = assn_dir + "\\od_veh_trips_" + p + ".mtx"
        if GetFileInfo(f) <> null then do
            RunMacro("TRMG2 export one matrix", f, out_dir + "\\od_veh_trips_" + p, fptr)
        end
        else WriteLine(fptr, "SKIP od_veh_trips_" + p + ".mtx (not found)")
    end

    // ---------- 3. TRANSIT SKIMS (period x access x transit mode) ----------
    // TRMG2 names vary by build; grab every .mtx in the transit skim folder.
    if GetDirectoryInfo(tskim_dir, "Directory") <> null then do
        a = GetDirectoryInfo(tskim_dir + "\\*.mtx", "File")
        for i = 1 to a.length do
            nm = Substitute(a[i][1], ".mtx", "", 1)
            RunMacro("TRMG2 export one matrix", tskim_dir + "\\" + a[i][1],
                     out_dir + "\\transit_" + nm, fptr)
        end
    end
    else WriteLine(fptr, "SKIP transit skims: folder not found -> " + tskim_dir)

    // ---------- 4. OPTIONAL: roadway skims (sov/hov) for one feedback iter ----------
    if GetDirectoryInfo(rskim_dir, "Directory") <> null then do
        a = GetDirectoryInfo(rskim_dir + "\\*.mtx", "File")
        for i = 1 to a.length do
            nm = Substitute(a[i][1], ".mtx", "", 1)
            RunMacro("TRMG2 export one matrix", rskim_dir + "\\" + a[i][1],
                     out_dir + "\\rdwy_" + nm, fptr)
        end
    end

    // ---------- 5. turn_prohibitions.bin: empty or populated? ----------
    tp = input_net + "\\turn_prohibitions.bin"
    if GetFileInfo(tp) <> null then do
        v = OpenTable("tp", "FFB", {tp, })
        nrows = GetRecordCount(v, )
        CloseView(v)
        WriteLine(fptr, "turn_prohibitions.bin rows = " + String(nrows) +
                  (if nrows = 0 then "  (EMPTY in this scenario)" else "  (POPULATED)"))
    end
    else WriteLine(fptr, "turn_prohibitions.bin NOT FOUND -> " + tp +
                   "  (may be absent/empty in the base year)")

    CloseFile(fptr)
    ShowMessage("TRMG2 export complete. See " + out_dir + " and export_log.txt")
endMacro


/*  Export one .mtx to OMX (all cores) + one CSV per core. */
Macro "TRMG2 export one matrix" (mtx_file, out_stub, fptr)
    mtx = OpenMatrix(mtx_file, )
    cores = GetMatrixCoreNames(mtx)

    // OMX (preferred): whole matrix, all cores. Requires TransCAD 9.0+.
    ok = 0
    mc0 = CreateMatrixCurrency(mtx, cores[1], , , )
    CopyMatrix(mc0, {{"File Name", out_stub + ".omx"}})       // .omx extension -> OMX
    if GetFileInfo(out_stub + ".omx") <> null then ok = 1

    // CSV per core (works on every version; the guaranteed fallback)
    for i = 1 to cores.length do
        mc = CreateMatrixCurrency(mtx, cores[i], , , )
        ExportMatrix(mc, cores[i], "Rows", "CSV", out_stub + "_" + cores[i] + ".csv", )
    end
    WriteLine(fptr, "matrix " + out_stub + ": " + String(cores.length) + " cores" +
              (if ok = 1 then " (OMX + CSV)" else " (CSV only)"))
    mtx = null
endMacro
