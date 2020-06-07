
from git import Repo
import datetime as dt 
import os 

carpeta = 'LoadFiles'
# listamos los archivos que se cargaran
entries = os.listdir()
for archivo in entries: 
    file_list = []
    #Separamos solo los archivos excel del directorio
    if archivo.endswith('.xlsx'):
        
        
        # Designamos el nombre del repositorio al cual se subiran los archivos

        repo_dir = 'GIT_UPDATE'
        repo = Repo(repo_dir)
        file_list = [archivo]
        print(file_list)
        #Se define el commit que se utilizara
        commit_message = 'Datos de series y portafolio fecha' + str(dt.datetime.now())
        print(commit_message)
        #Se realiza el add de los archivos, que listamos antes
        repo.index.add(file_list)
        #Se realiza el commit
        repo.index.commit(commit_message)
        #Se define la branche 
        origin = repo.remote('origin')
        origin.push()