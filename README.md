# FST ForgePolish

A specialized high-performance hard-surface smoothing and polishing toolset for Blender. 

Ideal for cleaning up retopologized meshes from ZBrush, removing surface irregularities, and ensuring flawless surface fidelity before final beveling and subdivision stages.

## Installation

The addon supports **Blender 4.2 LTS through 5.1**.

1. Download the latest `FST_ForgePolish_v1.0.x.zip` from the [Releases](../../releases) page.
2. Open Blender and go to **Edit > Preferences > Add-ons** (or **Extensions** in 4.2+).
3. Click **Install...** (or the down arrow icon -> Install from Disk).
4. Select the downloaded `.zip` file.
5. Enable the addon by ticking the checkbox.

## Where is it located in Blender?

Once installed, the FST ForgePolish panel can be accessed in the **3D Viewport**. 
Open the Sidebar (press `N`) and navigate to the **Edit** tab. 

*Note: The FaceSets utility tools will only become active when you are in **Edit Mode**.*

---

## Workflow & Tools

FST ForgePolish relies on identifying "inner" regions and "boundaries". You can easily define these regions using the built-in FaceSets tools.

### 1. FaceSets Workflow (Preparation)
To get the best polishing results on complex hard-surface models, you can isolate flat planes and curved transitions using FaceSets.

* **Edges to FaceSets:** In Edit Mode, select the sharp edges that define your main surface transitions. Click this button to automatically create distinct FaceSets via a flood-fill algorithm based on your edge selection.
* **FaceSets to Select:** Quickly re-select the boundary edges that separate your neighboring FaceSets.

### 2. Polishing Modes (The Core)
When you click **Polish**, the tool modifies the mesh topology using one of two highly optimized algorithms (calculated via NumPy for maximum performance):

* **Standard HC (Volume Preserve):** Smooths the surface while utilizing HC correction to reduce volume loss. It maintains the original proportions of your mesh while relaxing the uneven topology.
* **Tension First (Surface Shrink):** Skips volume compensation and prioritizes tension reduction. This is an aggressive polish that shrinks the surface slightly but results in incredibly clean, sharp, and tight topology.

---

## Parameters

* **Iterations:** Controls how many times the smoothing operation is repeated. Higher values result in a smoother mesh but may take slightly longer on very dense topology.
* **Corners:** A crucial feature for hard-surface modeling. It locks boundary corners that are sharper than the specified angle, preventing your mechanical corners from melting away during the smoothing process. Set to `0` to disable.
* **Selected:** If enabled, the tool will only polish the currently selected vertices/faces and completely lock the rest of the mesh in place.
* **Advanced Options:**
  Expand the advanced panel to get low-level control over the polish tuning:
  * **Inner (Smooth / Preserve):** Adjust the single-step smoothing strength and volume preservation *inside* the continuous face sets.
  * **Boundary (Smooth / Preserve):** Adjust the smoothing and preservation specifically on the borders separating the face sets.

## Multilingual Support

FST ForgePolish automatically adapts to your Blender interface language. Built-in languages include:
* English
* Chinese (Simplified / Traditional)
* Japanese
* Spanish
* French
* German
* Russian

## License
GNU General Public License v3.0
