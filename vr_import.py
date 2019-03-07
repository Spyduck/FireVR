# Import JanusVR from URL/filesystem
import os
import urllib.request as urlreq
import gzip
import bpy
from mathutils import Vector, Matrix, Euler
from math import radians
import re
import bs4
import traceback
import sys
import json
from hashlib import md5 as hashlib_md5
current_module = sys.modules[__name__]
primitive_path = 'file:///'+os.path.join(os.path.dirname(current_module.__file__), 'primitives')
primitives = ['capsule', 'cone', 'cube', 'cylinder', 'pipe', 'plane', 'pyramid', 'sphere', 'torus']
def s2v(s):
	try:
		return [float(c) for c in s.split(" ")]
	except:
		return [0,0,0]

def s2p(s):
	v = s2v(s)
	return [v[0], -v[2], v[1]]

def s2lp(s):
	v = s2v(s)
	return [v[0], v[2], v[1]]

'''
def fromFwd(zdir):
	ydir = [0,1,0]
	xdir = Vector(ydir).cross(Vector(zdir))
	zdir = (zdir[0], zdir[2], zdir[1])
	ydir = [0,0,1]
	mtrx = Matrix([xdir, zdir, ydir])
	return mtrx
'''
def fromFwd(v):
	d = Vector(v)
	z = d.normalized()
	x = Vector([0,1,0]).cross(z).normalized()
	y = z.cross(x).normalized()
	return Matrix([x, y, z])

def neg(v):
	return [-e for e in v]

def rel2abs(base, path):
	if path.startswith("../"):
		parentdir = base[:-2 if base.endswith("/") else -1].rsplit("/", 1)[0]
		return os.path.join(parentdir, path[3:])

	return path

class AssetObjectObj:

	def __init__(self, basepath, workingpath, tag):
		self.downloaded_imgfiles = {}
		self.basepath = basepath
		self.workingpath = workingpath
		self.tag = tag
		self.id = tag["id"]
		self.src = tag["src"]
		self.sourcepath = os.path.dirname(self.src)
		self.mtl = tag.attrs.get("mtl", None)
		self.mtl_basepath = None
		self.loaded = False
		self.imported = False
		self.objects = []

	def abs_source(self, base, path):
		base = rel2abs(self.basepath, base)
		if path.startswith("file:///"):
			path = path
		if path.startswith("./"):
			path = path[2:]
		if path.startswith("/") or path.startswith("http://") or path.startswith("https://"):
			return path
		elif path.startswith("../"):
			return rel2abs(base, path)
		if base.startswith("http://") or base.startswith("https://"):
			return os.path.join(base, path).replace('\\','/')
		return os.path.join(base, path).replace('\\','/')
	
	def md5(self, url):
		m = hashlib_md5()
		m.update(url.encode('utf-8'))
		return m.hexdigest()
	
	def abs_target(self, path, source=None):
		if source:
			name, ext = os.path.splitext(os.path.basename(path))
			if ext == '.gz':
				_, ext = os.path.splitext(os.path.basename(name))
				ext += '.gz'
			return os.path.join(self.workingpath, self.md5(source)+ext)
		return os.path.join(self.workingpath, os.path.basename(path))

	# Moves resources to the working directory
	def retrieve(self, path, base=None):
		exists = True
		if base is None:
			base = self.basepath
		if path.startswith('file:///'):
			return os.path.abspath(path[8:]), exists
		source = self.abs_source(base, path)
		target = self.abs_target(path, source=source)
		if not os.path.exists(os.path.abspath(target)):
			exists = False
			print('Retrieving '+source, 'to', target)
			try:
				urlreq.urlretrieve(source, target)
			except:
				print('Error getting '+source)
				print(traceback.format_exc())
				return '', exists
		else:
			print('Reusing '+source, 'as', target)
		if path.endswith(".gz"):
			if not os.path.exists(target[:-3]):
				exists = False
				with gzip.open(target, 'rb') as infile:
					with open(target[:-3], 'wb') as outfile:
						outfile.write(infile.read())

			return target[:-3], exists
		return target, exists

	def load(self):

		if self.loaded:
			return
		self.orig_src = self.abs_source(self.basepath, self.src)
		if self.src is not None:
			self.src, _ = self.retrieve(self.src)
			exists = False
			if self.mtl is None:
				with open(self.src,'r') as f:
					mtllib = re.search(r"mtllib (.*?)$", f.read(), re.MULTILINE)
					if mtllib:
						try:
							self.mtl_basepath = self.abs_source( os.path.dirname(self.abs_source(self.basepath, self.tag["src"])), mtllib.group(1))
							self.mtl, exists = self.retrieve(self.mtl_basepath)
						except Exception as e:
							print(e)
							self.mtl = None
			if self.mtl is not None:
				if self.mtl_basepath:
					mtlpath = os.path.dirname(self.mtl_basepath)
				else:
					mtlpath = os.path.dirname(self.abs_source(self.basepath,self.mtl))
				src_mtl = self.mtl
				if not exists:
					self.mtl, exists = self.retrieve(self.mtl)
				imgfiles = []
				if os.path.exists(self.mtl) and not exists:
						
					with open(self.mtl, "r") as mtlfile:
						#imgfiles = re.findall(r"\b\w*\.(?:jpg|gif|png)", mtlfile.read())
						imgfiles = re.findall(r"((\S*?)\.(?:jpg|jpeg|gif|png))", mtlfile.read())
					
					for imgfile in imgfiles:
						if imgfile[0] not in self.downloaded_imgfiles:
							if not os.path.exists(os.path.join(self.workingpath, imgfile[0])):
								self.downloaded_imgfiles[imgfile[0]], _ = self.retrieve(imgfile[0], mtlpath)

					# rewrite mtl to point to local file
					with open(self.abs_target(self.mtl, source=src_mtl), "r") as mtlfile:
						file = mtlfile.read()
					for imgfile in imgfiles:
						#file = file.replace(self.downloaded_imgfiles[imgfile[0]], os.path.basename(imgfile[0]))
						file = file.replace(imgfile[0], os.path.basename(self.downloaded_imgfiles[imgfile[0]]))
					with open(self.mtl, "w") as mtlfile:
						mtlfile.write(file)
			self.loaded = True
			print('Loaded asset.')
	#An .obj can include multiple objects!
	def instantiate(self, tag):
		if not self.imported:
			#bpy.ops.object.select_all(action='DESELECT')
			self.load()
			self.imported = True
			objects = list(bpy.data.objects)
			if self.mtl is not None:
				if self.mtl[:-4] != self.src[:-4]:
					# rewrite obj to use correct mtl
					replaced = False
					file = ""
					with open(self.abs_target(self.src, source=self.orig_src), "r") as mtlfile:
						for line in mtlfile.read().split('\n'):
							if line[:6] == 'mtllib':
								file = file + 'mtllib ' + os.path.basename(self.mtl) + '\n'
								replaced = True
							else:
								file = file + line + '\n'
						if replaced == False:
							file = 'mtllib ' + os.path.basename(self.mtl) + '\n' + file
					with open(self.abs_target(self.src[:-4]+"_"+os.path.basename(self.mtl[:-4])+".obj"), "w") as mtlfile:
						mtlfile.write(file)
					bpy.ops.import_scene.obj(filepath=self.src[:-4]+"_"+os.path.basename(self.mtl[:-4])+".obj", axis_up="Y", axis_forward="-Z")
				else:
					bpy.ops.import_scene.obj(filepath=self.src, axis_up="Y", axis_forward="-Z")
			else:
				bpy.ops.import_scene.obj(filepath=self.src, axis_up="Y", axis_forward="-Z")
			bpy.ops.object.transform_apply(location = True, scale = True, rotation = True)
			self.objects = [o for o in list(bpy.data.objects) if o not in objects]
			obj = bpy.context.selected_objects[0]
			obj.name = self.id
		else:
			newobj = []
			for obj in self.objects:
				bpy.ops.object.select_all(action='DESELECT')
				bpy.ops.object.select_pattern(pattern=obj.name)
				bpy.ops.object.duplicate(linked=True)
				newobj.append(bpy.context.selected_objects[0])
			self.objects = newobj

		for obj in self.objects:
			scale = s2v(tag.attrs.get("scale", "1 1 1"))
			obj.scale = (scale[0], scale[2], scale[1])
			obj.rotation_euler = get_rotation_euler(tag)
			location = s2p(tag.attrs.get("pos", "0 0 0"))
			obj.location = location #translate(obj.location, location)
		return list(self.objects)

def get_rotation_euler(tag):
	if "xdir" in tag.attrs or "ydir" in tag.attrs or "zdir" in tag.attrs:
		xdir = s2v(tag.attrs.get("xdir", "1 0 0"))
		ydir = s2v(tag.attrs.get("ydir", "0 1 0"))
		zdir = s2v(tag.attrs.get("zdir", "0 0 1"))
		zdir = (zdir[0], zdir[2], zdir[1])
		ydir = (ydir[0], ydir[2], ydir[1])
		return (Matrix([xdir, zdir, ydir])).to_euler()
	elif 'rotation' in tag.attrs:
		rotation = s2v(tag.attrs.get('rotation', '0 0 0'))
		rotation = (rotation[0], rotation[1], rotation[2])
		return (radians(rotation[0]), radians(rotation[1]), radians(rotation[2]))
	else:
		return fromFwd(s2v(tag.attrs.get("fwd", "0 0 1"))).to_euler()

def read_html(operator, scene, filepath, path_mode, workingpath):
	#FEATURE import from ipfs://
	if filepath.startswith("http://") or filepath.startswith("https://"):
		splitindex = filepath.rfind("/")
		basepath = filepath[:splitindex+1]
		basename = filepath[splitindex+1:]
	else:
		basepath = "file:///" + os.path.dirname(filepath)
		basename = os.path.basename(filepath)
		filepath = "file:///" + filepath

	source = urlreq.urlopen(filepath.replace('\\','/'))
	html = source.read()
	#fireboxrooms = bs4.BeautifulSoup(html, "html.parser").findAll("fireboxroom")
	fireboxrooms = bs4.BeautifulSoup(html, "html.parser").find_all(lambda tag: tag.name.lower()=='fireboxroom')
	if len(fireboxrooms) == 0:
		# no fireboxroom, remove comments and try again
		html = re.sub("(<!--)", "", html.decode('utf-8'), flags=re.DOTALL).encode('utf-8')
		html = re.sub("(-->)", "", html.decode('utf-8'), flags=re.DOTALL).encode('utf-8')
	soup = bs4.BeautifulSoup(html, "html.parser")
	fireboxrooms = soup.findAll("fireboxroom")

	if len(fireboxrooms) == 0:
		operator.report({"ERROR"}, "Could not find the FireBoxRoom tag")
		return

	fireboxroom = fireboxrooms[0]

	rooms = fireboxroom.findAll("room")
	if rooms is None:
		operator.report({"ERROR"}, "Could not find the Room tag")
		return

	room = rooms[0]

	# Reset all changes in case of later error? Undo operator?
	# Prevent having to specify defaults twice? (on external load and addon startup)
	scene.janus_room_gravity = float(room.attrs.get("gravity", 9.8))
	scene.janus_room_walkspeed = float(room.attrs.get("walk_speed", 1.8))
	scene.janus_room_runspeed = float(room.attrs.get("run_speed", 5.4))
	scene.janus_room_jump = float(room.attrs.get("jump_velocity", 5))
	scene.janus_room_clipplane[0] = float(room.attrs.get("near_dist", 0.0025))
	scene.janus_room_clipplane[1] = float(room.attrs.get("far_dist", 500))
	scene.janus_room_teleport[0] = float(room.attrs.get("teleport_min_dist", 5))
	scene.janus_room_teleport[1] = float(room.attrs.get("teleport_min_dist", 100))
	scene.janus_room_defaultsounds = bool(room.attrs.get("default_sounds", True))
	scene.janus_room_cursorvisible = bool(room.attrs.get("cursor_visible", True))
	scene.janus_room_fog = bool(room.attrs.get("fog", False))
	scene.janus_room_fog_density = float(room.attrs.get("fog_density", 500))
	scene.janus_room_fog_start = float(room.attrs.get("fog_start", 500))
	scene.janus_room_fog_end = float(room.attrs.get("fog_end", 500))
	scene.janus_room_fog_col = s2v(room.attrs.get("fog_col", "100 100 100"))
	scene.janus_room_locked = bool(room.attrs.get("locked", False))

	jassets = {}

	assets = fireboxroom.findAll("assets")
	if assets is None:
		operator.report({"INFO"}, "No assets found")
		return

	all_assets = assets[0].findAll("assetobject")
	for primitive_id in primitives:
		asset_src = '<AssetObject id="'+primitive_id+'" src="'+os.path.join(primitive_path, primitive_id+'.obj')+'"/>'
		asset = bs4.BeautifulSoup(asset_src, 'html.parser').find()
		all_assets.append(asset)
	for asset in all_assets:
		#dae might be different!
		#assets with same basename will conflict (e.g. from different domains)
		
		if asset.attrs.get("src", None) is not None:
			if asset["src"].lower().endswith(".obj") or asset["src"].lower().endswith(".obj.gz"):
				jassets[asset["id"]] = AssetObjectObj(basepath, workingpath, asset)
			elif asset["src"].lower().endswith(".dae") or asset["src"].lower().endswith(".dae.gz"):
				jassets[asset["id"]] = AssetObjectDae(basepath, workingpath, asset)
			elif asset["src"].lower().endswith(".gltf") or asset["src"].lower().endswith(".gltf.gz"):
				jassets[asset["id"]] = AssetObjectGltf(basepath, workingpath, asset)
			elif asset["src"].lower().endswith(".fbx") or asset["src"].lower().endswith(".fbx.gz"):
				jassets[asset["id"]] = AssetObjectFbx(basepath, workingpath, asset)
			else:
				continue
		else:
			continue

	objects = room.findAll("object")
	if objects is None:
		operator.report({"INFO"}, "No objects found")
		return

	for obj in objects:
		try:
			id = obj.get('id')
			if id:
				asset = jassets.get(id)
				if asset:
					asset.instantiate(obj)
				elif id.startswith('http://') or id.startswith('https://'):
					asset_src = '<AssetObject id="'+id+'" src="'+id+'"/>'
					new_asset = bs4.BeautifulSoup(asset_src, 'html.parser').find('assetobject')
					jassets[new_asset['id']] = AssetObjectGltf(basepath, workingpath, new_asset)
					asset = jassets.get(id)
					asset.instantiate(obj)
		except:
			print(traceback.format_exc())

def translate(vec1, vec2):
	return (vec1[0]+vec2[0], vec1[1]+vec2[1], vec1[2]+vec2[2])
def multiply(vec1, vec2):
	return (vec1[0]*vec2[0], vec1[1]*vec2[1], vec1[2]*vec2[2])

class AssetObjectDae(AssetObjectObj):
	def instantiate(self, tag):
		self.load()
		if not self.imported:
			before = len(bpy.data.objects)
			self.imported = True
			bpy.ops.object.select_all(action='DESELECT')
			bpy.ops.wm.collada_import(filepath=self.src)
			bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', object=True, obdata=True)
			bpy.ops.object.transform_apply(location = True, scale = True, rotation = True)
			self.objects = bpy.context.selected_objects
			for obj in self.objects:
				obj.name = self.id
		else:
			newobj = []
			for obj in self.objects:
				bpy.ops.object.select_all(action='DESELECT')
				bpy.ops.object.select_pattern(pattern=obj.name)
				bpy.ops.object.duplicate(linked=True)
				#newobj.append(bpy.context.selected_objects[0])
				newobj.extend(bpy.context.selected_objects)
			self.objects = newobj

		for obj in self.objects:
			scale = s2v(tag.attrs.get("scale", "1 1 1"))
			obj.scale = (scale[0], scale[2], scale[1])
			if "xdir" in tag.attrs or "ydir" in tag.attrs or "zdir" in tag.attrs:
				xdir = s2v(tag.attrs.get("xdir", "1 0 0"))
				ydir = s2v(tag.attrs.get("ydir", "0 1 0"))
				zdir = s2v(tag.attrs.get("zdir", "0 0 1"))
				zdir = (zdir[0], zdir[2], zdir[1])
				ydir = (ydir[0], ydir[2], ydir[1])
				obj.rotation_euler = (Matrix([xdir, zdir, ydir])).to_euler()
			else:
				obj.rotation_euler = fromFwd(s2v(tag.attrs.get("fwd", "0 0 1"))).to_euler()

			obj.location = s2p(tag.attrs.get("pos", "0 0 0"))

	def load(self):

		if self.loaded:
			return

		if self.src:
			src_orig = self.abs_source(os.path.dirname(self.basepath+"0"), self.src)
			self.src, exists = self.retrieve(self.src)
			if not exists and self.src:
				self.parse_dae(self.src,src_orig)
			self.loaded = True

	def parse_dae(self, path, dae_url):
		f = open(path,'r')
		line = ''
		output = ''
		line = f.readline()
		while line != '':
			m = re.search('<init_from>(.*?)\.(jpg|png|gif|bmp)</init_from>', line)
			if m is not None:
				img = self.abs_source(os.path.dirname(dae_url), m.group(1)+'.'+m.group(2))
				if not os.path.exists(os.path.join(self.workingpath, img)):
					#img = self.retrieve(img, os.path.dirname(self.abs_source(self.basepath, self.src)))
					img, _ = self.retrieve(img, os.path.dirname(self.abs_source(self.basepath, self.src)))
					if img:
						img = img[img.rfind(os.path.sep)+1:].replace('\\','/')
					line = re.sub('<init_from>(.*?)</init_from>', '<init_from>'+img+'</init_from>', line)
				output += line
			else:
				output += line
			line = f.readline()
		f.close()
		f = open(path,'w')
		f.write(output)
		f.close()

class AssetObjectGltf(AssetObjectObj):
	def instantiate(self, tag):
		self.load()
		if not self.imported:
			before = len(bpy.data.objects)
			self.imported = True
			bpy.ops.object.select_all(action='DESELECT')
			objects = list(bpy.data.objects)
			bpy.ops.import_scene.gltf(filepath=self.src)
			bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', object=True, obdata=True)
			bpy.ops.object.transform_apply(location = True, scale = True, rotation = True)
			self.objects = [o for o in list(bpy.data.objects) if o not in objects]
			#bpy.context.selected_objects = self.objects
			for obj in self.objects:
				obj.select_set(state=True)
			bpy.ops.object.join()
			bpy.ops.object.select_all(action='DESELECT')
			self.objects = [o for o in list(bpy.data.objects) if o not in objects]
			for obj in self.objects:
				obj.select_set(state=True)
				obj.name = self.id
		else:
			newobj = []
			for obj in self.objects:
				bpy.ops.object.select_all(action='DESELECT')
				bpy.ops.object.select_pattern(pattern=obj.name)
				bpy.ops.object.duplicate(linked=True)
				newobj.extend(bpy.context.selected_objects)
			self.objects = newobj

		for obj in self.objects:
			scale = s2v(tag.attrs.get("scale", "1 1 1"))
			obj.scale = (scale[0], scale[2], scale[1])
			if "xdir" in tag.attrs or "ydir" in tag.attrs or "zdir" in tag.attrs:
				xdir = s2v(tag.attrs.get("xdir", "1 0 0"))
				ydir = s2v(tag.attrs.get("ydir", "0 1 0"))
				zdir = s2v(tag.attrs.get("zdir", "0 0 1"))
				zdir = (zdir[0], zdir[2], zdir[1])
				ydir = (ydir[0], ydir[2], ydir[1])
				obj.rotation_mode = 'XYZ'
				obj.rotation_euler = (Matrix([xdir, zdir, ydir])).to_euler()
			else:
				obj.rotation_euler = fromFwd(s2v(tag.attrs.get("fwd", "0 0 1"))).to_euler()

			obj.location = s2p(tag.attrs.get("pos", "0 0 0"))
	def load(self):
		if self.loaded:
			return

		if self.src:
			src_orig = self.abs_source(os.path.dirname(self.basepath), self.src)
			self.src, exists = self.retrieve(self.src)
			if not exists and self.src:
				self.parse_gltf(self.src,src_orig)
			self.loaded = True

	def parse_gltf(self, path, gltf_url):
		changed_file = False
		content = None
		with open(path, 'rb') as f:
			try:
				content = json.loads(str(f.read(), 'utf-8'))
			except: # probably gltf binary, ignore
				return
			# fetch .bin
			buffers = content.get('buffers',[])
			for i in range(0,len(buffers)):
				buffer = buffers[i]
				uri = buffer.get('uri',None)
				if uri:
					if uri.startswith('data:'):
						continue
					uri_fn = self.abs_source(os.path.dirname(gltf_url), uri)
					if not os.path.exists(os.path.join(self.workingpath, uri_fn)):
						bin, _ = self.retrieve(uri_fn, os.path.dirname(self.abs_source(os.path.dirname(gltf_url), uri_fn)))
						content['buffers'][i]['uri'] = bin
						changed_file = True
			# fetch images
			images = content.get('images',[])
			for i in range(0,len(images)):
				image = images[i]
				uri = image.get('uri',None)
				if uri:
					if uri.startswith('data:'):
						continue
					uri_fn = self.abs_source(os.path.dirname(gltf_url), uri)
					if not os.path.exists(os.path.join(self.workingpath, uri_fn)):
						img, _ = self.retrieve(uri_fn, os.path.dirname(self.abs_source(os.path.dirname(gltf_url), uri_fn)))
						content['images'][i]['uri'] = img
						changed_file = True
		if changed_file:
			with open(path, 'wb') as f:
				f.write(bytes(json.dumps(content), 'utf-8'))
	
class AssetObjectFbx(AssetObjectObj):
	def instantiate(self, tag):
		self.load()
		if not self.imported:
			before = len(bpy.data.objects)
			self.imported = True
			bpy.ops.object.select_all(action='DESELECT')
			objects = list(bpy.data.objects)
			bpy.ops.import_scene.fbx(filepath=self.src, bake_space_transform=True, global_scale=100.0, use_manual_orientation=False, axis_up='Z', axis_forward='-Y')#, axis_up='Y', axis_forward='-Z')
			bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', object=True, obdata=True)
			bpy.ops.object.transform_apply(location = True, scale = True, rotation = True)
			self.objects = [o for o in list(bpy.data.objects) if o not in objects]
			for obj in self.objects:
				obj.select_set(state=True)
				bpy.context.view_layer.objects.active = obj
			bpy.ops.object.join()
			bpy.ops.object.select_all(action='DESELECT')
			self.objects = [o for o in list(bpy.data.objects) if o not in objects]
			for obj in self.objects:
				obj.select_set(state=True)
				obj.name = self.id
				bpy.context.view_layer.objects.active = obj
		else:
			newobj = []
			for obj in self.objects:
				bpy.ops.object.select_all(action='DESELECT')
				bpy.ops.object.select_pattern(pattern=obj.name)
				bpy.ops.object.duplicate(linked=True)
				newobj.extend(bpy.context.selected_objects)
			self.objects = newobj

		for obj in self.objects:
			scale = s2v(tag.attrs.get("scale", "1 1 1"))
			obj.scale = (scale[0], scale[2], scale[1])
			
			obj.rotation_euler = get_rotation_euler(tag)
			obj.rotation_mode = 'XYZ'

			obj.location = s2p(tag.attrs.get("pos", "0 0 0"))
	def load(self):
		if self.loaded:
			return

		if self.src:
			src_orig = self.abs_source(os.path.dirname(self.basepath), self.src)
			self.src, exists = self.retrieve(self.src)
			self.loaded = True

def load(operator, context, filepath, path_mode="AUTO", relpath="", workingpath="FireVR/tmp"):
	read_html(operator, context.scene, filepath, path_mode, workingpath)
