import os
import shutil

def main():
    src_dir = "../human-activity-detection"
    dest_dir = "models/activity"
    
    os.makedirs(dest_dir, exist_ok=True)
    
    graph_name = "frozen_inference_graph.pb"
    labels_name = "labels.txt"
    
    src_graph = os.path.join(src_dir, graph_name)
    dest_graph = os.path.join(dest_dir, graph_name)
    
    src_labels = os.path.join(src_dir, labels_name)
    dest_labels = os.path.join(dest_dir, labels_name)
    
    print(f"Creating directory {dest_dir}...")
    
    if os.path.exists(src_graph):
        print(f"Copying {src_graph} to {dest_graph}...")
        shutil.copy2(src_graph, dest_graph)
    else:
        print(f"Source graph not found at {src_graph}")
        
    if os.path.exists(src_labels):
        print(f"Copying {src_labels} to {dest_labels}...")
        shutil.copy2(src_labels, dest_labels)
    else:
        print(f"Source labels not found at {src_labels}")
        
    print("Done!")

if __name__ == "__main__":
    main()
