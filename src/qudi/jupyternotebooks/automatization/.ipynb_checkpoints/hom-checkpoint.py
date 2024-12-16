#%%
import numpy as np
import os
from TimeTagger import FileWriter, FileReader
# %%
folder = r'Z:\Vlad\SnV\HOM\dumps'
fw = tagger.write_into_file(os.path.join(folder, 'test.ttbin'), channels=[1,2,3])
# %%
fw.getTotalSize()
# %%
# fw.split()
# %%
fr = FileReader(os.path.join(folder, 'test.ttbin'))
# %%
fr.getData(100).getTimestamps()
# %%
