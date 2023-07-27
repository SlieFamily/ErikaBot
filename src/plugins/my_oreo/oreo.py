import cv2
import base64
import os

img_path = os.path.dirname(__file__)
img_path = img_path.replace("\\", "/")

O = cv2.imread(img_path+"/O.png",cv2.IMREAD_UNCHANGED)
R = cv2.imread(img_path+"/R.png",cv2.IMREAD_UNCHANGED)
Ob = cv2.imread(img_path+"/Ob.png",cv2.IMREAD_UNCHANGED)
empty =  cv2.imread(img_path+"/empty.png",cv2.IMREAD_UNCHANGED)
# 对馅缩放
R = cv2.resize(R,
                     (int(0.9*R.shape[1]),int(0.9*R.shape[0])),
                     interpolation=cv2.INTER_AREA
                     )

def AddPng(img,px):
      new_img = cv2.copyMakeBorder(img,px,
                                                 0,0,0,
                                                 cv2.BORDER_CONSTANT,
                                                 value = [255,255,255]
                                                 )
      _,_,_,alpha_channel = cv2.split(new_img)
      alpha_channel[:px,:] = 0
      return new_img

def AddOtop(img):
      roi = img[0:410,0:600]
      Ogray = cv2.cvtColor(O,cv2.COLOR_BGR2GRAY)

      _,mask = cv2.threshold(Ogray,253,255,cv2.THRESH_BINARY)
      mask_inv = cv2.bitwise_not(mask)

      roi_bg = cv2.bitwise_and(roi,roi,mask=mask)
      O_fg = cv2.bitwise_and(O,O,mask=mask_inv)
      dst = cv2.add(roi_bg,O_fg)
      img[0:410,0:600] = dst
      return img

def AddR(img):
      roi = img[0:369,30:570]
      Rgray = cv2.cvtColor(R,cv2.COLOR_BGR2GRAY)

      _,mask = cv2.threshold(Rgray,253,255,cv2.THRESH_BINARY)
      mask_inv = cv2.bitwise_not(mask)

      roi_bg = cv2.bitwise_and(roi,roi,mask=mask)
      R_fg = cv2.bitwise_and(R,R,mask=mask_inv)
      dst = cv2.add(roi_bg,R_fg)
      img[0:369,30:570] = dst
      return img

def AddOb(img):
      roi = img[0:410,0:600]
      Ogray = cv2.cvtColor(Ob,cv2.COLOR_BGR2GRAY)

      _,mask = cv2.threshold(Ogray,253,255,cv2.THRESH_BINARY)
      mask_inv = cv2.bitwise_not(mask)

      roi_bg = cv2.bitwise_and(roi,roi,mask=mask)
      Ob_fg = cv2.bitwise_and(Ob,Ob,mask=mask_inv)
      dst = cv2.add(roi_bg,Ob_fg)
      img[0:410,0:600] = dst
      return img

def Img2base64(img_cv2):
      img = cv2.imencode(".png",img_cv2)[1]
      img_code = str(base64.b64encode(img))[2:-1]
      return "base64://"+img_code

def CreateImg(string):
    name = string.strip()
    if name.find("给") != -1:
    	return img_path+'/oregay.jpg'
    if len(name) > 50:
    	return False
    image = Ob.copy() if name[-1] == '奥' else AddR(empty.copy())

    for i in range(0,len(name)-2):
            if (name[len(name)-i-1] == "奥") & (name[len(name)-i-2] == "利"):
                image = AddR(AddPng(image,40))
            elif (name[len(name)-i-1] == "利") & (name[len(name)-i-2] == "利"):
                image = AddR(AddPng(image,60))
            elif (name[len(name)-i-1] == "利") & (name[len(name)-i-2] == "奥"):
                image = AddOb(AddPng(image,84))
            elif (name[len(name)-i-1] == "奥") & (name[len(name)-i-2] == "奥"):
                image = AddOb(AddPng(image,64))

      # 对顶层单独处理
    if (name[0] == "奥") & (name[1] == "利"):
        image = AddPng(image, 84)
        image = AddOtop(image)
    elif (name[0] == "奥") & (name[1] == "奥"):
        image = AddPng(image, 64)
        image = AddOtop(image)
    elif (name[0] == "利") & (name[1] == "奥"):
        image = AddPng(image, 40)
        image = AddR(image)
    elif (name[0] == "利") & (name[1] == "利"):
        image = AddPng(image, 60)
        image = AddR(image)

    cv2.imwrite(img_path+'/oreo.png', image)
    return str(img_path+'/oreo.png')

