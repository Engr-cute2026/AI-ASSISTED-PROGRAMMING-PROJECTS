import tkinter as tk
from tkinter import messagebox
from openstaadpy import os_analytical

# ==========================================
# MAIN FUNCTION TO CREATE MODEL IN STAAD
# ==========================================
def create_staad_model():
    try:
        staad = os_analytical.connect()
        if staad is None:
            messagebox.showerror("Error", "STAAD.Pro is not open.")
            return

        geo = staad.Geometry
        prop = staad.Property
        sup = staad.Support
        load = staad.Load

        # --- UNITS FEET KIP ---
        staad.SetInputUnits(1,0)
        staad.SaveModel(True)

        # ===============================
        # GET GEOMETRY INPUTS
        # ===============================
        nodes = {}
        for i in range(1, 17):
            x = float(entries[f"x{i}"].get())
            y = float(entries[f"y{i}"].get())
            z = float(entries[f"z{i}"].get())
            nodes[i] = (x,y,z)
            geo.CreateNode(i,x,y,z)

        # ===============================
        # MEMBERS (static connectivity)
        # ===============================
        member_incidence = {
            1:(1,3),2:(3,7),3:(2,6),4:(6,8),5:(3,4),6:(4,5),7:(5,6),
            8:(7,12),9:(12,14),10:(14,16),11:(15,16),12:(13,15),13:(8,13),
            14:(9,12),15:(9,14),16:(11,14),17:(11,15),18:(10,15),
            19:(10,13),20:(7,9),21:(9,11),22:(10,11),23:(8,10)
        }

        for mid,(n1,n2) in member_incidence.items():
            geo.CreateBeam(mid,n1,n2)

        # ===============================
        # PROPERTIES
        # ===============================
        cc = 1
        w14 = prop.CreateBeamPropertyFromTable(cc,"W14X90",0,0,0)
        w10 = prop.CreateBeamPropertyFromTable(cc,"W10X49",0,0,0)
        w21 = prop.CreateBeamPropertyFromTable(cc,"W21X50",0,0,0)
        w18 = prop.CreateBeamPropertyFromTable(cc,"W18X35",0,0,0)
        angle = prop.CreateAnglePropertyFromTable(cc,"L40404",0,0,0)

        prop.AssignBeamProperty([1,3,4],w14)
        prop.AssignBeamProperty([2],w10)
        prop.AssignBeamProperty([5,6,7],w21)
        prop.AssignBeamProperty(list(range(8,14)),w18)
        prop.AssignBeamProperty(list(range(14,24)),angle)
        prop.AssignMaterialToMember("STEEL",list(range(1,24)))
        prop.AssignBetaAngle([3,4],90.0)

        # ===============================
        # SUPPORTS
        # ===============================
        fixed_id = sup.CreateSupportFixed()
        pinned_id = sup.CreateSupportPinned()
        sup.AssignSupportToNode([1],fixed_id)
        sup.AssignSupportToNode([2],pinned_id)

        # ===============================
        # LOAD CASES
        # ===============================
        gravity_factor = float(entry_gravity.get())
        lateral_load = float(entry_lateral.get())

        # Dead + Live Load Case
        case1 = load.CreateNewPrimaryLoadEx2("DEAD AND LIVE LOAD",0,1)
        load.SetLoadActive(case1)
        load.AddSelfWeightInXYZ(2,-gravity_factor)
        load.AddNodalLoad([4,5],0,-gravity_factor*15,0,0,0,0)
        load.AddNodalLoad([11],0,-gravity_factor*35,0,0,0,0)
        load.AddMemberUniformForce(list(range(8,14)),2,-gravity_factor*0.9,0,0,0)
        load.AddMemberUniformForce([6],2,-gravity_factor*1.2,0,0,0)

        # Wind / Lateral Load Case
        case2 = load.CreateNewPrimaryLoadEx2("LATERAL WIND",3,2)
        load.SetLoadActive(case2)
        load.AddMemberUniformForce([1,2],4,lateral_load,0,0,0)
        load.AddMemberUniformForce(list(range(8,11)),2,-lateral_load,0,0,0)

        # Load Combination 75%
        comb3 = load.CreateNewLoadCombination("75% DL LL WL",3)
        load.AddLoadAndFactorToCombination(3,1,0.75)
        load.AddLoadAndFactorToCombination(3,2,0.75)

        # Save and Analyze
        staad.SaveModel(True)
        staad.Command.PerformAnalysis(0)

        messagebox.showinfo("Success", "3D Model Created & Analyzed Successfully!")

    except Exception as e:
        messagebox.showerror("Error", str(e))


# ==========================================
# GUI SETUP
# ==========================================
root = tk.Tk()
root.title("STAAD 3D Model Builder")
root.geometry("600x800")

# Node entries
entries = {}
tk.Label(root,text="Enter Node Coordinates (X,Y,Z) for 16 Nodes",font=("Arial",12,"bold")).pack(pady=5)

frame_nodes = tk.Frame(root)
frame_nodes.pack()

for i in range(1,17):
    tk.Label(frame_nodes,text=f"Node {i}").grid(row=i-1,column=0)
    entries[f"x{i}"] = tk.Entry(frame_nodes,width=6)
    entries[f"x{i}"].grid(row=i-1,column=1)
    entries[f"y{i}"] = tk.Entry(frame_nodes,width=6)
    entries[f"y{i}"].grid(row=i-1,column=2)
    entries[f"z{i}"] = tk.Entry(frame_nodes,width=6)
    entries[f"z{i}"].grid(row=i-1,column=3)

# Default node coordinates
default_coords = [
    (0.0,0.0,0.0),(30.0,0.0,0.0),(0.0,20.0,0.0),(10.0,20.0,0.0),
    (20.0,20.0,0.0),(30.0,20.0,0.0),(0.0,35.0,0.0),(30.0,35.0,0.0),
    (7.5,35.0,0.0),(22.5,35.0,0.0),(15.0,35.0,0.0),(5.0,38.0,0.0),
    (25.0,38.0,0.0),(10.0,41.0,0.0),(20.0,41.0,0.0),(15.0,44.0,0.0)
]
for i, coord in enumerate(default_coords,1):
    entries[f"x{i}"].insert(0,str(coord[0]))
    entries[f"y{i}"].insert(0,str(coord[1]))
    entries[f"z{i}"].insert(0,str(coord[2]))

# Load Inputs
tk.Label(root,text="Load Inputs",font=("Arial",12,"bold")).pack(pady=10)
tk.Label(root,text="Gravity Factor").pack()
entry_gravity = tk.Entry(root); entry_gravity.pack()
entry_gravity.insert(0,"1.0")

tk.Label(root,text="Lateral Load").pack()
entry_lateral = tk.Entry(root); entry_lateral.pack()
entry_lateral.insert(0,"0.6")

# Create Model Button
tk.Button(root,text="Create & Analyze 3D Model",bg="green",fg="white",
          command=create_staad_model).pack(pady=20)

root.mainloop()
