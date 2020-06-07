
from git import Repo
import datetime as dt 
import os 

carpeta = 'LoadFiles'
# listamos los archivos que se cargaran
entries = os.listdir(carpeta)
for archivo in entries: 
    file_list = []
    #Separamos solo los archivos excel del directorio
    if archivo.endswith('.xlsx'):
        print(archivo) 
        file_list.append(carpeta+'/'+archivo)

# Designamos el nombre del repositorio al cual se subiran los archivos
print(file_list)
repo_dir = 'Git_update'
repo = Repo(repo_dir)


#Se define el commit que se utilizara
commit_message = 'Datos de series y portafolio fecha' + str(dt.datetime.now())
#Se realiza el add de los archivos, que listamos antes
repo.index.add(carpeta)
#Se realiza el commit
repo.index.commit(commit_message)
#Se define la branche 
origin = repo.remote('origin')
origin.push()