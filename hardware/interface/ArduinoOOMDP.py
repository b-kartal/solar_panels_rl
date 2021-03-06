from simple_rl.mdp.oomdp.OOMDPClass import OOMDP
from simple_rl.mdp.oomdp.OOMDPObjectClass import OOMDPObject
import sys
sys.path.append("../experiments") #TODO: reconfigure directory structure so this doesn't happen
import solarOOMDP.solar_helpers as sh
import time as t
import datetime
import serial
#using OpenCV and PIL for image handling instead of SimpleCV
from cv2 import VideoCapture
from PIL import Image

from solarOOMDP.SolarOOMDPStateClass import SolarOOMDPState

class ArduinoOOMDP(OOMDP):
	'''
	Creates an OOMDP for the Arduino-based solar tracker.
	Communicates with the arduino + recieves images from camera.
	'''
	
	ACTIONS = ['F', 'B', 'N'] # forward, backward, do nothing
	
	ATTRIBUTES = ['angle_AZ', 'angle_ALT', 'angle']
	CLASSES = ['agent', 'sun', 'time', 'worldPosition', 'panel']
	
	def __init__(self, 
				date_time,
				serial_loc='/dev/ttyACM0', 
				baud=9600,
				use_img=True,
				panel_step=0.1, #radians, used to specify command to arduino
				timestep=30,
				latitude_deg=41.82,
				longitude_deg=-71.4128):
					
		self.image_dims = 16 #use for downsampling image from camera
		self.use_img = use_img
		# Global information
		self.latitude_deg = latitude_deg # positive in the northern hemisphere
		self.longitude_deg = longitude_deg # negative reckoning west from prime meridian in Greenwich, England
		self.timestep = timestep #timestep in minutes
		self.panel_step = panel_step
		
		#initialize communication with the arduino
		self.ser = serial.Serial(serial_loc, baud, timeout=120)
		self.ser.flushOutput()
		self.ser.flushInput()
		self.ser.write("INIT")
		
		print "establishing communication with panel" 
		result = self.ser.readline() #result should take the form of RECV,<current angle>
		
		
		
		
		if result.startswith("RECV"):
			initial_angle_ns = float(result.split(",")[1])
			print "connection established, initial angle along ns axis is {}".format(initial_angle_ns) 
		else:
			raise Exception("ERROR: invalid response from arduino: {}".format(result))
			
		
		
		if self.use_img:
			#initialize camera connection
			self.cam = VideoCapture(0)
			t.sleep(0.2)  # wait for camera
			
			#take image
			start_pixels = self._capture_img()
		else:
			start_pixels = None
		
		# Time stuff.
		self.init_time = date_time
		self.time = date_time
		
		#create initial state
		init_state = self._create_state(0, initial_angle_ns, start_pixels, self.init_time)
		
		OOMDP.__init__(self, ArduinoOOMDP.ACTIONS, self.objects, self._transition_func, self._reward_func, init_state=init_state)


	def _capture_img(self, target_size=(16,16),):
		'''
		Captures and processes image. Returns a flattened list of pixel values. 
		'''
		ret, frame = self.cam.read()
		
		#create PIL image
		img = Image.fromarray(frame)
		processed = img.convert("L").resize(target_size)
		
		return list(processed.getdata())
		
		
	def _create_state(self, angle_ew, angle_ns, pixels, time):
		'''
		Creates an OOMDP state from the provided panel angle, time, and image.
		Image is a flattened array of image pixels, provided by _capture_img
		'''
		
		self.objects = {attr : [] for attr in ArduinoOOMDP.CLASSES}
		
		panel_attributes = {'angle_ew':angle_ew, 'angle_ns':angle_ns}
		panel = OOMDPObject(attributes=panel_attributes, name='panel')
		self.objects["panel"].append(panel) #it's a list! 
		
		 # Sun.
		sun_attributes = {}
		sun_angle_AZ = sh._compute_sun_azimuth(self.latitude_deg, self.longitude_deg, time)
		sun_angle_ALT = sh._compute_sun_altitude(self.latitude_deg, self.longitude_deg, time)
		
		#NOTE: providing sun angle AND image 
		sun_attributes["angle_AZ"] = sun_angle_AZ
		sun_attributes["angle_ALT"] = sun_angle_ALT  
		
		if pixels:
			for idx, pix in enumerate(pixels):
				sun_attributes['pix' + str(idx)] = pix
			 
		
		sun = OOMDPObject(attributes=sun_attributes, name="sun")
		self.objects["sun"].append(sun)
		
		return SolarOOMDPState(self.objects, date_time=time, longitude=self.longitude_deg, latitude=self.latitude_deg, sun_angle_AZ = sun_angle_AZ, sun_angle_ALT = sun_angle_ALT)
		
		
	def _reward_func(self, state, action):
		'''
		Transmits action to the arduino, recieves reward + new state information
		'''
		
		#change command based on panel step
		
		command = "N"
		
		#NOTE: INVERTED AXIS
		if action == "F":
			command = "S{}".format(self.panel_step)
		elif action == "B":
			command = "S-{}".format(self.panel_step)
		elif action.startswith("P"):
			command = action
		
		self.ser.write(command)
		self.ser.flushOutput()
		
		print "transmitted command {} to arduino".format(command)
		
		#blocks until recieved info
		response = self.ser.readline().split(",") #contains reward,final angle
		
		print "flushing input buffer"
		self.ser.flushInput()
		
		print "recieved response {} from arduino".format(response)
		
		if response[0] == "":
			return 0 #no reward/ failure occured
			
		reward = float(response[0])
		angle_ns = float(response[1])
		
		#print "recieved reward of {}, angle is now {}".format(reward, angle)
		
		#take image
		pixels = self._capture_img() if self.use_img else None
		
		#step time
		self.time = datetime.datetime.now()
		
		#create new state
		self._next_state = self._create_state(0, angle_ns, pixels, self.time)
		#self._next_state.update() #I think this is called upon init and is redundant
		
		return reward
		
	def _transition_func(self, state, action):
		'''
		Returns the next state created by reward_func
		'''
		return self._next_state
		
	def _get_day(self):
		return self.time.timetuple().tm_yday

	def get_panel_step(self):
		return self.panel_step

	def get_reflective_index(self):
		return self.reflective_index

	def get_single_axis_actions(self):
		return ["N", "F", "B"]
		
if __name__=="__main__":
	#test OOMDP class
	current_time = datetime.datetime.now()
	oomdp = ArduinoOOMDP(current_time, use_img=True)
	reward = oomdp._reward_func(None, "B")
	next_state = oomdp._transition_func(None, "B")
	
		
