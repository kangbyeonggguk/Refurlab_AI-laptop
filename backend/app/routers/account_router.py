import secrets

from fastapi import APIRouter, Header,Form
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from starlette import status
from fastapi.security import OAuth2PasswordRequestForm
from core import util
from core.redis_config import redis_config
import httpx


from db.database import db
from crud import account_crud
from schemas import account_schema

from datetime import datetime
import pytz 
from core.sms_config import Settings as Settings
import random
from twilio.rest import Client

router = APIRouter(
)

#회원가입
@router.post("/accounts", status_code=status.HTTP_200_OK)
async def account_create(_account: account_schema.AccountCreate, session: Session = Depends(db.session)):
    account_crud.create_account(db=session, account=_account)

#로그인
@router.post("/accounts/login", response_model=account_schema.Token, status_code=status.HTTP_200_OK)
async def account_login(form_data: OAuth2PasswordRequestForm = Depends(),
                        session: Session = Depends(db.session)):
    account = account_crud.get_account(session, form_data.username)
    
    if not account or not account_crud.pwd_context.verify(form_data.password, account.password) or not account.platform_type=="R":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect id or password",
            headers={"WWW-Authenticate": "Bearer"}
        )

    rd = redis_config()
    two_weeks = 1209600
    refresh_token = util.create_refresh_token(account.account_id)
    rd.setex(refresh_token, two_weeks, account.account_id)

    print(account.platform_type)
    print(account.admin)

    return {"access_token": util.create_access_token(account.account_id),
            "refresh_token": refresh_token,
            "platform_type":account.platform_type,
            "admin":account.admin}

#토큰 리프레시
@router.post("/accounts/refresh-token", status_code=status.HTTP_200_OK)
async def account_refresh_token_check(refresh_token_key: str):
    rd = redis_config()
    check = rd.get(refresh_token_key)

    if check is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return {"access_token": util.create_access_token(int(check))}

#로그아웃
@router.post("/accounts/logout", status_code=status.HTTP_200_OK)
async def account_logout(refresh_token_key: str):
    rd = redis_config()
    rd.delete(refresh_token_key)


#소셜 로그인
@router.post("/accounts/login/{sns}",status_code=status.HTTP_200_OK,response_model=account_schema.Token)
async def account_sns_login(sns: str,oauthcode: str = Form(None),session: Session = Depends(db.session) ):
    
    if oauthcode is None:#인가 코드 없으면 에러
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect oathcode",
            headers={"WWW-Authenticate": "Bearer"}
        )
    else:
        oauth_client=util.get_oauth_client(sns)
       
      
        platform_type,user_url,token_url,data,account="","","",{},""
        if sns=="kakao":
            platform_type="K"
            user_url = "https://kapi.kakao.com/v2/user/me"
            token_url = "https://kauth.kakao.com/oauth/token"
            data = {
                "grant_type": "authorization_code",
                "client_id": oauth_client.get_value_based_on_parameter("client_id"), 
                "redirect_uri": oauth_client.get_value_based_on_parameter("redirect_uri"),
                "code": oauthcode,
            } 
        elif sns=="naver":
            platform_type="N"
            user_url = "https://openapi.naver.com/v1/nid/me"
            token_url = "https://nid.naver.com/oauth2.0/token"
            data = {
                "grant_type": "authorization_code",
                "client_id": oauth_client.get_value_based_on_parameter("client_id"), 
                "client_secret": oauth_client.get_value_based_on_parameter("client_secret_id"), 
                "redirect_uri": oauth_client.get_value_based_on_parameter("redirect_uri"),
                "code": oauthcode,
                "state":"false",
            } 
       
        try:
            async with httpx.AsyncClient() as client:#토큰 요청
                response = await client.post(token_url, data=data)
                response_data = response.json()
    
            #토큰을 받게 될 시 유저 정보 가져오기    
            headers = {"Authorization": f"Bearer {response_data['access_token']}"}
            async with httpx.AsyncClient() as client:
                user_response = await client.get(user_url, headers=headers)
                user_data = user_response.json()
            
            id=""
            if platform_type=="K":
                id=user_data["id"]
                account=account_schema.AccountCreate(
                    id=str(user_data["id"]),
                    platform_type=platform_type,
                    admin=0,
                    password="kakaoid!",
                    nickname=user_data["properties"]["nickname"],
                    email="kakao@kakao.com",
                    phonenumber="010-1111-1111",
                    create_date=datetime.now(pytz.timezone("Asia/Seoul"))
                )
            elif platform_type=="N":
                id=user_data["response"]["id"]
                account=account_schema.AccountCreate(
                    id=str(user_data["response"]["id"]),
                    platform_type=platform_type,
                    admin=0,
                    password="naverid!",
                    nickname=user_data["response"]["name"],
                    email=user_data["response"]["email"],
                    phonenumber=user_data["response"]["mobile"],
                    create_date=datetime.now(pytz.timezone("Asia/Seoul"))
                )
            
            # #유저 정보가 없다면 저장
            check = account_crud.get_account(session, id)
         
            if not check:
                account_crud.create_account(db=session, account=account)  
                check = account_crud.get_account(session, id)

            #리프레시 토큰과 액세스 토큰 발급 및 리턴
            rd = redis_config()
            two_weeks = 1209600
            refresh_token = util.create_refresh_token(check.account_id)
            rd.setex(refresh_token, two_weeks, check.account_id)

            return {"access_token": util.create_access_token(check.account_id),
            "refresh_token": refresh_token,"platform_type":check.platform_type,
            "admin":check.admin}
        
        except httpx.HTTPError as http_error:
            # HTTP 요청이 실패한 경우에 대한 처리
            raise HTTPException(status_code=401, detail="Unauthorized")

#문자 전송
@router.post("/send",status_code=status.HTTP_200_OK)
async def account_send_sms(request_data: dict,session: Session = Depends(db.session),token: str = Header(None)):
    phone = request_data.get("phone", "")
    #해당 유저 휴대폰 번호인지 확인
    phonecheck=account_crud.get_account_info(db=session, token=token)
    if phonecheck.phonenumber.replace("-", "")!=phone:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    else:
        auth_num = str(random.randint(100000, 999999))
     
        rd = redis_config()

        rd.setex(phone, 600, auth_num)
     
        sms_setting = Settings()
        twilio_client = Client(sms_setting.twilio_account_sid, sms_setting.twilio_auth_token)
        try:
         
            message = twilio_client.messages.create(
                to="+82"+phone,
                from_=sms_setting.twilio_phone_number,  # 업데이트된 전화번호 사용
                body="리퍼 연구소 개인 정보 변경 인증번호:"+auth_num
            )
            
            # 성공한 경우 응답
            return {"result":True}
            
        except Exception as e:
            # 실패한 경우 에러 응답
            print(e)
            raise HTTPException(status_code=401, detail="Unauthorized")
    
#문자 인증 확인
@router.post("/verify",status_code=status.HTTP_200_OK)
async def account_sms_verify(request_data: dict):
    phone = request_data.get("phone")
    auth_num = request_data.get("auth_num")
    rd = redis_config()
    check=rd.get(phone)
    if check.decode('utf-8')==auth_num:
        rd.delete(phone)
        return {"result":True} 
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/callback")
async def callback(
        code: str, state: Optional[str] = None, oauth_client=Depends(util.get_oauth_client)
):
    token_response = await oauth_client.get_tokens(code, state)
    return {"response": token_response}


@router.get("/refresh")
async def callback(
        oauth_client=Depends(util.get_oauth_client),
        refresh_token: str = Depends(util.get_authorization_token)
):
    token_response = await oauth_client.refresh_access_token(
        refresh_token=refresh_token)

    return {"response": token_response}


@router.get("/sns_account", dependencies=[Depends(util.login_required)])
async def get_sns_account(
        oauth_client=Depends(util.get_oauth_client()),
        access_token: str = Depends(util.get_authorization_token),
):
    user_info = await oauth_client.get_user_info(access_token=access_token)
    return {"account": user_info}

#아이디 중복 확인
@router.get("/accounts/duplicate", status_code=status.HTTP_200_OK)
async def account_id_check(id: str, session: Session = Depends(db.session)):
    check = account_crud.get_account(session, id)

    if check:
        raise HTTPException(status_code=400)

#내 정보 수정
@router.patch("/accounts", status_code=status.HTTP_200_OK)
async def account_info_update(account: account_schema.AccountUpdate, session: Session = Depends(db.session), token: str = Header(None)):
    account_crud.update_account(db=session, token=token, account=account)

#회원 정보 확인
@router.get("/accounts", status_code=status.HTTP_200_OK)
async def account_info_get(session: Session = Depends(db.session), token: str = Header(None)):
    result = account_crud.get_account_info(db=session, token=token)
   

    if result:
        account_info = {
            "id": result.id,
            "nickname": result.nickname,
            "email": result.email,
            "phonenumber": result.phonenumber
         }
        return {"response": account_info}