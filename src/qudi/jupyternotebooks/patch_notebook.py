import json

notebook_path = "c:/Users/yy3/GIT/squdi/src/qudi/jupyternotebooks/ple_auto_points_scan.ipynb"

with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

# Find Setup Coordinates cell
for cell in nb['cells']:
    if cell['cell_type'] == 'code' and "PLE_LINES_PER_SCAN =" in "".join(cell['source']):
        new_source = []
        for line in cell['source']:
            new_source.append(line)
            if "PLE_LINES_PER_SCAN =" in line:
                new_source.append("\n")
                new_source.append("# Voltage shift applied to the DLC PRO laser for lower and higher passes\n")
                new_source.append("# (Adjust this to match the voltage equivalent of your ~22 GHz range)\n")
                new_source.append("LASER_VOLTAGE_SHIFT_V = 20.0\n")
        cell['source'] = new_source
        break

# Find Execution Loop cell (it has `_stop_flag = False` as first line)
for cell in nb['cells']:
    if cell['cell_type'] == 'code' and len(cell['source']) > 0 and '_stop_flag = False\n' in cell['source'][0]:
        new_source = [
            "_stop_flag = False\n",
            "\n",
            "def run_automation():\n",
            "    global _stop_flag\n",
            "    _stop_flag = False\n",
            "    \n",
            "    print(f\"Starting Automated Scan Sequence...\")\n",
            "    \n",
            "    # Read the current central voltage from the DLC Pro laser\n",
            "    orig_laser_voltage = dl_pro_laser.get_pc_voltage_set()\n",
            "    \n",
            "    # Three passes defined by their offset multipliers\n",
            "    # 0 = Central, -1 = Lower voltages (-shift), 1 = Higher voltages (+shift)\n",
            "    voltage_passes = [\n",
            "        ('Central',  0),\n",
            "        ('Lower',   -1),\n",
            "        ('Higher',   1)\n",
            "    ]\n",
            "    \n",
            "    for pass_name, offset_multi in voltage_passes:\n",
            "        if _stop_flag:\n",
            "            print(\"\\n--- Sequence Interrupted by User ---\")\n",
            "            break\n",
            "            \n",
            "        new_laser_voltage = orig_laser_voltage + (offset_multi * LASER_VOLTAGE_SHIFT_V)\n",
            "        \n",
            "        print(f\"\\n{'='*50}\")\n",
            "        print(f\"=== Starting PASS: {pass_name} ===\")\n",
            "        print(f\"=== Laser PC Voltage Set to: {new_laser_voltage:.3f} V ===\")\n",
            "        print(f\"{'='*50}\\n\")\n",
            "        \n",
            "        # Apply new voltage range to the hardware\n",
            "        dl_pro_laser.set_pc_voltage(new_laser_voltage)\n",
            "        time.sleep(2.0) # give laser time to stabilize at new voltage\n",
            "        \n",
            "        for idx, (x, y) in enumerate(POINTS_XY):\n",
            "            if _stop_flag:\n",
            "                print(\"\\n--- Sequence Interrupted by User ---\")\n",
            "                break\n",
            "                \n",
            "            # Include the pass_name in the tag so records aren't overwritten\n",
            "            tag = f\"P_{idx:03d}_{pass_name}_X{x*1e6:.2f}_Y{y*1e6:.2f}\"\n",
            "            print(f\"\\n[{pass_name} Pass] [Point {idx+1}/{len(POINTS_XY)}] Moving to X: {x*1e6:.2f} \u00b5m, Y: {y*1e6:.2f} \u00b5m\")\n",
            "            \n",
            "            # 1. Move Confocal Scanner\n",
            "            confocal.set_target_position({'x': x, 'y': y}, move_blocking=True)\n",
            "            time.sleep(1.0) # wait for settling\n",
            "            \n",
            "            # 2. Get Starting Wavelength\n",
            "            start_wl = get_wavelength(wavemeter)\n",
            "            print(f\"   --> Start Wavelength: {start_wl:.5f} nm\")\n",
            "            \n",
            "            # 3. Apply PLE lines setting in GUI\n",
            "            ple_gui_app._mw.number_of_repeats_SpinBox.setValue(PLE_LINES_PER_SCAN)\n",
            "            ple_gui_app._mw.number_of_repeats_SpinBox.editingFinished.emit()\n",
            "            time.sleep(0.2)\n",
            "            \n",
            "            # 4. Trigger PLE Scan from GUI\n",
            "            print(f\"   --> Running PLE scan...\")\n",
            "            ple_gui_app._mw.actionToggle_scan.setChecked(True)\n",
            "            ple_gui_app.toggle_scan()\n",
            "            time.sleep(1.0)\n",
            "            \n",
            "            # 5. Wait for PLE scan to complete\n",
            "            while ple_scan.module_state() != 'idle':\n",
            "                if _stop_flag:\n",
            "                    ple_scan.stop_scan()\n",
            "                    break\n",
            "                time.sleep(0.5)\n",
            "                \n",
            "            ple_gui_app._mw.actionToggle_scan.setChecked(False)\n",
            "            \n",
            "            if _stop_flag:\n",
            "                continue\n",
            "            \n",
            "            # 6. Get Stopping Wavelength\n",
            "            stop_wl = get_wavelength(wavemeter)\n",
            "            print(f\"   --> Stop Wavelength:  {stop_wl:.5f} nm\")\n",
            "            \n",
            "            # 7. Collect and Save Data using the PLE GUI app method\n",
            "            scan_data = ple_gui_app.scan_data\n",
            "            if scan_data is not None:\n",
            "                # Update the text field in GUI so it visually reflects the tag\n",
            "                ple_gui_app.save_path_widget.saveTagLineEdit.setText(tag)\n",
            "                \n",
            "                # Extract standard parameters from GUI (colors, paths via checkboxes)\n",
            "                cbar_range = ple_gui_app._mw.matrix_widget.image_widget.levels\n",
            "                \n",
            "                if ple_gui_app.save_path_widget.DailyPathCheckBox.isChecked():\n",
            "                    folder = None\n",
            "                    ple_gui_app.save_path_widget.currPathLabel.setText(\"Default\")\n",
            "                else:\n",
            "                    folder = ple_gui_app._save_folderpath\n",
            "                    \n",
            "                # Combine Controller widget metadata (if any) with wavemeter info\n",
            "                meta = {}\n",
            "                if ple_gui_app._controller_logic is not None:\n",
            "                    meta.update(ple_gui_app._mw.Controller_widget.params)\n",
            "                    \n",
            "                meta['voltage_pass'] = pass_name\n",
            "                meta['laser_pc_voltage'] = new_laser_voltage\n",
            "                meta['automated_point_index'] = idx\n",
            "                meta['confocal_target_x_m'] = x\n",
            "                meta['confocal_target_y_m'] = y\n",
            "                meta['wavemeter_start_wl_nm'] = start_wl\n",
            "                meta['wavemeter_stop_wl_nm'] = stop_wl\n",
            "\n",
            "                print(f\"   --> Triggering GUI save with tag: {tag}\")\n",
            "                # Emit the GUI's signal to save the data exactly as clicking \"Save Data\" would!\n",
            "                ple_gui_app.sigSaveScan.emit(\n",
            "                    scan_data,\n",
            "                    ple_gui_app._scanning_logic._channel,\n",
            "                    ple_gui_app._scanning_logic._fit_container,\n",
            "                    cbar_range,\n",
            "                    tag,\n",
            "                    folder,\n",
            "                    meta\n",
            "                )\n",
            "                print(f\"   --> Save triggered to pathway: {'Default' if folder is None else folder}\")\n",
            "            else:\n",
            "                print(f\"   --> [ERROR] No scan data found in ple_gui_app to save for point {idx+1}.\")\n",
            "                \n",
            "            time.sleep(0.5) # pause between points\n",
            "            \n",
            "    print(\"\\nDone!\\n\")\n",
            "    \n",
            "    # Cleanup: restore original laser voltage\n",
            "    print(f\"Restoring original laser PC voltage: {orig_laser_voltage:.3f} V\")\n",
            "    dl_pro_laser.set_pc_voltage(orig_laser_voltage)\n",
            "\n",
            "def stop_automation():\n",
            "    global _stop_flag\n",
            "    _stop_flag = True\n",
            "    print(\"Stopping flag set. Wait for current scan to abort.\")\n"
        ]
        cell['source'] = new_source
        break

# clear outputs so it's clean
for cell in nb['cells']:
    if 'outputs' in cell:
        cell['outputs'] = []

with open(notebook_path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
